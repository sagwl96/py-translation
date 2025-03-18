# py-translation
A transparent window based translation app. Drag the window over the content you want to translate and press the spacebar.

Created conda environment with python=3.9

Using pyqt6
pip install PyQt6

Installed opencv
pip install opencv-python

V3
- transparent window area
- position of corners
- screenshot of area

V4
- removed button and replaced with SpaceBar

V5
- OCR on the captured screenshot
- Graceful close

Need pytesseract for that
pip install pytesseract

V6
- translate to english

Using googletrans for now
pip install googletrans==4.0.0-rc1

V7
- translate line by line
- understand German letters

sudo apt-get install tesseract-ocr-deu

V8
- Replace detected text with translated text in the imshow window

V9
- Perform better translation using paragraph detection and replace with text with same number of lines

V10 - main
- add a loading indicator when translation is happening in the background


Requirements:

PIP:
- PyQt6
- opencv-python
- pytesseract
- googletrans==4.0.0-rc1

System:
sudo apt-get install tesseract-ocr-deu
