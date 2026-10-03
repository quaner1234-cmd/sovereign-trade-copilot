"""Fail closed on staged secrets, private company markers, local paths and logs.

Reads known secret values from this process and Windows environment registry;
never prints a value, matching excerpt or credential. Review synthetic provenance
separately: pattern matching cannot establish that arbitrary business data is safe.
"""
import os
import re
import subprocess
import sys

NAMES = ("CSCS_INFERENCE_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN")
secrets = {os.environ[n] for n in NAMES if os.environ.get(n)}
if os.name == "nt":
    import winreg
    for hive, path in ((winreg.HKEY_CURRENT_USER,"Environment"),
                       (winreg.HKEY_LOCAL_MACHINE,r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(hive,path) as key:
                for n in NAMES:
                    try:
                        value,_=winreg.QueryValueEx(key,n)
                        if value:secrets.add(str(value))
                    except FileNotFoundError:pass
        except FileNotFoundError:pass

patterns = {
    "token_prefix": re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "local_path": re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]|/(?:Users|home)/"),
    "private_company_marker": re.compile(r"B[o]wins|Lianch[u]ang|联[创]",re.I),
}
paths=subprocess.check_output(["git","ls-files","-z"],text=True).split("\0")
failures=[]
for path in filter(None,paths):
    if path.endswith((".log",".err",".tmp")) or (os.path.basename(path).startswith(".env") and not path.endswith(".env.example")):
        failures.append((path,"private_or_temporary_file"))
    data=subprocess.check_output(["git","show",":"+path])
    text=data.decode("utf-8",errors="replace")
    if any(s in text for s in secrets):failures.append((path,"known_secret_value"))
    for name,rx in patterns.items():
        if rx.search(text):failures.append((path,name))
for path,rule in failures:print("FAIL",path,rule)
print("STAGED SCAN:","FAIL" if failures else "PASS", "files="+str(len(list(filter(None,paths)))),"known_secret_values_checked="+str(len(secrets)))
sys.exit(1 if failures else 0)
