# Instant Translator (Performance Edition)

A high-performance, real-time screen translation tool written in Python using PyQt6. It captures a transparent area of your screen, runs Optical Character Recognition (OCR) to detect text (supporting German, English, and more), and overlays the English translation directly on top of the original text with a clean, semi-transparent UI.

## Features

*   **Transparent Overlay:** Translates text in-place while keeping the application window frame transparent.
*   **Dual OCR Engine Support:** Fallback mechanics between Tesseract OCR and PaddleOCR.
*   **Fast Translations:** Dual mode supporting ultra-fast offline translation (via Argos Translate) or parallelized online translation (via Google Translate).
*   **Smart Layout Reconstruction:** Merges word-level OCR outputs back into natural lines and paragraph boxes to prevent disjointed word-by-word translations.
*   **Keyboard Controls:**
    *   `Space`: Capture the selected area and translate.
    *   `Alt` (Hold): Temporarily hide translation overlays to see the original text.
    *   `Escape`: Clear all current overlays.

---

## Prerequisites

Before setting up the Python environment, you need to install **Tesseract OCR** on your system.

### Windows
1. Download the installer from [UB Mannheim's Tesseract page](https://github.com/UB-Mannheim/tesseract/wiki).
2. Run the installer and complete the setup.
3. Add the Tesseract installation path (usually `C:\Program Files\Tesseract-OCR`) to your system's **PATH** environment variable.

### macOS
Install via Homebrew:
```bash
brew install tesseract tesseract-lang

```

### Linux (Debian/Ubuntu)

Install via apt:

```bash
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-deu

```

---

## Installation & Setup

Follow these steps to set up a virtual environment and run the application.

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd <your-repo-folder>

```

### 2. Create a Virtual Environment (`venv`)

Create a clean, isolated Python environment:

* **Windows:**
```bash
python -m venv venv
venv\Scripts\activate

```


* **macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate

```



### 3. Install Dependencies

Upgrade pip and install the required packages:

```bash
pip install --upgrade pip
pip install PyQt6 opencv-python numpy pytesseract deep-translator

```

*(Optional)* If you want to use offline translation, install the Argos Translate package:

```bash
pip install argostranslate

```

---

## Running the Application

Make sure your virtual environment is active, then run:

```bash
python main.py

```

### How to use:

1. Position the transparent window over the German text you want to translate.
2. Press **Space** to trigger the translation.
3. Hold **Alt** to quickly peak at the original text underneath.
4. Press **Escape** to clear the translation boxes and start over.
