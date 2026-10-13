# Design truth

Canvas: 1920 x 1080. Content ends at y=886. Footer provides playback/approval disclosure.
Ground #f7f8f4; ink #183329; accent #315d45; muted #4c6358; warning #815b15. Generic system-ui font. Headline 58 px, phase title 40 px, explanatory copy 29 px, small disclosure 23 px.
Layout: left narrative lane x=80, width=555; right actual screenshot x=735, y=195, width=1105, height=650. Static crop magnifies the actual browser UI; no invented UI. A continuous progress bar represents elapsed film time. Phase entrances use short opacity/translate tweens. No arbitrary camera drift.

The 13 October captures use the normal in-app browser viewport. The image crop
is adjusted to those captures, rather than resizing the browser for appearance.
The current UI and its recorded-playback/approval disclosures remain observable.
