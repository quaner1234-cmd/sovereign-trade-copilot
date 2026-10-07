"""Company-source coverage and authorization boundaries; synthetic data only."""
import base64
import io
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import company_import as C
import light_harness as H
import light_server as S
import source_reader as R


class CompanyImportTests(unittest.TestCase):
    def upload(self, text, name='conditions.md'):
        data=text.encode('utf-8') if isinstance(text,str) else text
        return {'kind':'file','name':name,'content_base64':base64.b64encode(data).decode()}

    def test_full_text_is_preserved_without_model_or_truth_upgrade(self):
        text='\n# Conditional terms\nFor unlined vests only.\nMOQ 240 pcs; quantity basis requires confirmation.\n'
        with patch.object(H.llm_client,'chat') as model:
            result=C.import_source(self.upload(text))
        model.assert_not_called()
        self.assertEqual(result['text'],text)
        self.assertEqual(result['status'],'WORKING_VALUE')
        self.assertEqual(result['reading_state'],'read')
        self.assertEqual(len(result['sha256']),64)
        self.assertIn('accessed_at',result)
        self.assertNotIn('COMPANY_CONFIRMED',json.dumps(result))

    def test_text_encoding_and_filename_are_not_local_paths(self):
        text='适用于本次询盘。条件确认后才报价。'
        for raw in (text.encode('utf-8'),text.encode('utf-16'),text.encode('gb18030')):
            d=C.import_source(self.upload(raw,'C:\\private\\company.txt'))
            self.assertEqual(d['text'],text)
            self.assertEqual(d['source'],'company.txt')

    def test_invalid_oversized_or_empty_upload_does_not_return_source(self):
        for body in (self.upload('', 'empty.txt'),self.upload('text','.exe'),
                     self.upload(b'not-a-pdf','source.pdf'),
                     {'kind':'file','name':'source.md','content_base64':'invalid!'},
                     self.upload('x'*(C.MAX_TEXT+1))):
            with self.subTest(name=body.get('name')),self.assertRaises(C.ImportFailure):
                C.import_source(body)
        with patch.object(C,'MAX_BYTES',3),self.assertRaises(C.ImportFailure):
            C.import_source(self.upload('1234'))

    def test_pdf_boundary_is_text_only_and_no_temporary_file_remains(self):
        with patch.object(C,'pdf_text',return_value=('MOQ 240 pcs.\nFor vests only.',2)):
            d=C.import_source(self.upload(b'%PDF-synthetic','company.pdf'))
        self.assertEqual(d['pdf_pages'],2)
        self.assertEqual(d['reading_state'],'partially_read')
        self.assertIn('not verified',d['coverage'])
        self.assertEqual(d['status'],'WORKING_VALUE')
        with patch.object(C.shutil,'which',return_value=None),self.assertRaises(C.ImportFailure):
            C.pdf_text(b'%PDF-synthetic')

    def test_pdf_scan_encryption_and_page_limit_are_explicit_failures(self):
        executable=lambda name: name
        for info, extraction, message in [
            (type('Result',(),{'returncode':1,'stdout':b''})(),None,'password'),
            (type('Result',(),{'returncode':0,'stdout':b'Pages: 31\n'})(),None,'30 pages')]:
            with patch.object(C.shutil,'which',side_effect=executable), \
                 patch.object(C.subprocess,'run',return_value=info),self.assertRaisesRegex(C.ImportFailure,message):
                C.pdf_text(b'%PDF-synthetic')
        # A blank, image-only PDF is never marked read. The synthetic mock writes
        # no text into the real temporary output directory.
        def run(args,**kwargs):
            if args[0]=='pdfinfo':return type('Result',(),{'returncode':0,'stdout':b'Pages: 1\n'})()
            C.Path(args[-1]).write_text('',encoding='utf-8')
            return type('Result',(),{'returncode':0})()
        with patch.object(C.shutil,'which',side_effect=executable),patch.object(C.subprocess,'run',side_effect=run), \
             self.assertRaisesRegex(C.ImportFailure,'scanned PDF'):
            C.pdf_text(b'%PDF-synthetic')

    def test_website_is_one_public_page_reference_with_coverage(self):
        html=b'<html><head><title>Hidden title</title></head><body><p>MOQ <b>240</b> pcs.</p><script>invented capability</script><p>Only for vests.</p></body></html>'
        with patch.object(R,'fetch_bytes',return_value=(html,'text/html','https://example.invalid/terms')) as fetch:
            d=C.import_source({'kind':'website','url':'example.invalid/terms'})
        self.assertEqual(fetch.call_count,1)
        self.assertNotIn('invented capability',d['text'])
        self.assertNotIn('Hidden title',d['text'])
        self.assertIn('240',d['text'])
        self.assertIn('Only for vests',d['text'])
        self.assertEqual(d['status'],'PUBLIC_REFERENCE')
        self.assertEqual(d['reading_state'],'partially_read')
        self.assertIn('linked pages',d['coverage'])

    def test_website_network_disabled_or_blocked_keeps_unknown(self):
        with patch.dict(os.environ,{'SOURCE_READ_ENABLED':'0'}),patch.object(R,'fetch_bytes') as fetch, \
             self.assertRaisesRegex(C.ImportFailure,'disabled'):
            C.import_source({'kind':'website','url':'https://example.invalid'})
        fetch.assert_not_called()
        with patch.object(R,'fetch_bytes',side_effect=R.ReadFailure('non_public_destination')), \
             self.assertRaisesRegex(C.ImportFailure,'existing context is kept'):
            C.import_source({'kind':'website','url':'https://127.0.0.1'})

    def test_imported_reference_and_explicit_confirmation_use_existing_boundary(self):
        d=C.import_source(self.upload('MOQ 240 pcs for work vests only.'))
        fact={'statement':d['text'],'source':d['source'],'scope':'Work vests; this inquiry only','status':d['status']}
        body={'inquiry':'What is the minimum quantity?','company_context':[fact]}
        packet=H.normalize(body)
        self.assertEqual(H.brief_view(packet)['authorized_company_conditions'],[])
        self.assertEqual(len(H.brief_view(packet)['provisional_references_not_company_truth']),1)
        fact['status']='COMPANY_CONFIRMED'
        with patch.object(H.llm_client,'chat') as model:
            self.assertEqual(H.process(body)['status'],'confirmation_required')
        model.assert_not_called()
        packet=H.normalize(dict(body,context_authorized=True))
        self.assertEqual(H.brief_view(packet)['authorized_company_conditions'][0]['scope'],fact['scope'])

    def test_import_http_does_not_write_drafts_or_approvals(self):
        server=S.ThreadingHTTPServer(('127.0.0.1',0),S.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def post(body,origin=None):
            headers={'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            request=urllib.request.Request(base+'/context/import',data=json.dumps(body).encode(),headers=headers)
            with urllib.request.urlopen(request) as r:return json.load(r)
        before=H.digest(S.RECORDS)
        try:
            with patch.object(H.llm_client,'chat') as model:
                d=post(self.upload('Terms require internal confirmation.'))['document']
                self.assertEqual(d['status'],'WORKING_VALUE')
                model.assert_not_called()
            with self.assertRaises(urllib.error.HTTPError) as error:post(self.upload('text'),'https://untrusted.invalid')
            self.assertEqual(error.exception.code,403)
            with self.assertRaises(urllib.error.HTTPError) as error:post(self.upload('','empty.txt'))
            self.assertEqual(error.exception.code,400)
            self.assertEqual(H.digest(S.RECORDS),before)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main(verbosity=2)
