import sys
import cv2
import numpy as np
import pytesseract
from PyQt6 import QtCore, QtWidgets, QtGui
from googletrans import Translator

class OverlaySpinner(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Make the overlay cover the parent completely.
        self.setGeometry(parent.rect())
        # Opaque white background.
        self.setStyleSheet("background-color: white;")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.label = QtWidgets.QLabel(self)
        layout.addWidget(self.label)
        # Load spinner GIF.
        self.movie = QtGui.QMovie("spinner.gif")
        if self.movie.isValid():
            self.movie.setScaledSize(QtCore.QSize(100, 100))
        self.label.setMovie(self.movie)
        self.movie.start()

class TransparentCentralWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Fully transparent central widget.
        self.setAutoFillBackground(False)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
        
    def paintEvent(self, event):
        pass

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Transparent Content Window")
        # Initially, central widget is transparent.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.central = TransparentCentralWidget(self)
        self.setCentralWidget(self.central)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.central.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.resize(400, 300)
        self.translator = Translator()
        self.spinner_overlay = None  # We'll create this when needed.

    def get_transparent_area_geometry(self):
        geom = self.central.geometry()
        global_top_left = self.mapToGlobal(geom.topLeft())
        return global_top_left.x(), global_top_left.y(), geom.width(), geom.height()

    def showSpinner(self):
        # Remove transparency from main window while spinner is active.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.central.setStyleSheet("background-color: white;")
        # Create and show the overlay spinner covering the central widget.
        self.spinner_overlay = OverlaySpinner(self.central)
        self.spinner_overlay.show()
        self.spinner_overlay.raise_()
        QtWidgets.QApplication.processEvents()

    def hideSpinner(self):
        if self.spinner_overlay is not None:
            self.spinner_overlay.hide()
            self.spinner_overlay.deleteLater()
            self.spinner_overlay = None
        # Restore transparency of the main window.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.central.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
        QtWidgets.QApplication.processEvents()

    def capture_transparent_area(self):
        # --- 1) Capture screenshot of the transparent area ---
        screen = QtWidgets.QApplication.primaryScreen()
        x, y, w, h = self.get_transparent_area_geometry()
        screenshot = screen.grabWindow(0, x, y, w, h)
        qimage = screenshot.toImage()
        ptr = qimage.bits()
        ptr.setsize(qimage.sizeInBytes())
        img_rgba = np.array(ptr).reshape((qimage.height(), qimage.width(), 4))
        img_bgr = cv2.cvtColor(img_rgba, cv2.COLOR_RGBA2BGR)

        # --- 2) Run OCR and group words by paragraph then by line ---
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        ocr_data = pytesseract.image_to_data(gray, lang='eng+deu', output_type=pytesseract.Output.DICT)
        paragraphs = {}
        num_items = len(ocr_data['text'])
        for i in range(num_items):
            word = ocr_data['text'][i].strip()
            if not word:
                continue
            par_key = (ocr_data['block_num'][i], ocr_data['par_num'][i])
            line_num = ocr_data['line_num'][i]
            if par_key not in paragraphs:
                paragraphs[par_key] = {}
            if line_num not in paragraphs[par_key]:
                paragraphs[par_key][line_num] = []
            paragraphs[par_key][line_num].append(word)

        # --- 3) Show spinner overlay while translation is in progress ---
        self.showSpinner()

        final_lines = []
        for par_key in sorted(paragraphs.keys()):
            par_line_keys = sorted(paragraphs[par_key].keys())
            ocr_lines = []
            for ln in par_line_keys:
                line_text = " ".join(paragraphs[par_key][ln])
                ocr_lines.append(line_text)
            n_lines = len(ocr_lines)
            paragraph_text = " ".join(ocr_lines)
            try:
                detection = self.translator.detect(paragraph_text)
                if detection.lang != 'en':
                    translation = self.translator.translate(paragraph_text, dest='en')
                    translated_paragraph = translation.text
                else:
                    translated_paragraph = paragraph_text
            except Exception as e:
                print(f"Translation error for '{paragraph_text}':", e)
                translated_paragraph = paragraph_text

            words = translated_paragraph.split()
            if not words:
                final_lines.extend(ocr_lines)
            else:
                n_words = len(words)
                words_per_line = n_words // n_lines if n_lines > 0 else n_words
                split_lines = []
                start = 0
                for i in range(n_lines):
                    if i == n_lines - 1:
                        chunk = words[start:]
                    else:
                        chunk = words[start:start + words_per_line]
                    start += words_per_line
                    split_lines.append(" ".join(chunk))
                final_lines.extend(split_lines)

        self.hideSpinner()

        # --- 4) Create a new white image sized to fit the translated text ---
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.0
        thickness = 2
        line_spacing = 10
        margin = 20

        max_width = 0
        total_height = line_spacing
        line_heights = []
        for line in final_lines:
            (text_width, text_height), baseline = cv2.getTextSize(line, font, font_scale, thickness)
            max_width = max(max_width, text_width)
            lh = text_height + baseline
            line_heights.append(lh)
            total_height += lh + line_spacing

        new_img_width = max_width + 2 * margin
        new_img_height = total_height
        new_img = np.full((new_img_height, new_img_width, 3), 255, dtype=np.uint8)

        y_offset = line_spacing
        for i, line in enumerate(final_lines):
            (text_width, text_height), baseline = cv2.getTextSize(line, font, font_scale, thickness)
            cv2.putText(new_img, line, (margin, y_offset + text_height), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)
            y_offset += line_heights[i] + line_spacing

        # --- 5) Display the final translated image ---
        cv2.imshow("Translated Text (Line-by-Line)", new_img)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Space:
            self.capture_transparent_area()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        cv2.destroyAllWindows()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
