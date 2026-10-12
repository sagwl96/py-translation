"""Group OCR lines into columns and paragraphs."""
import numpy as np


def horizontal_overlap(rect1, rect2):
    x1, w1 = rect1
    x2, w2 = rect2
    left = max(x1, x2)
    right = min(x1 + w1, x2 + w2)
    if right <= left:
        return 0
    overlap = right - left
    min_width = min(w1, w2)
    return overlap / min_width if min_width > 0 else 0


# Lines whose text heights differ by more than this ratio start a new paragraph.
TEXT_H_RATIO = 1.35


def line_text_h(line):
    """Robust text height of a line (falls back to its rect height)."""
    return line.get('text_h') or line['rect'][3]


def make_paragraph(lines):
    full_text = " ".join([l['text'] for l in lines])
    line_rects = [l['rect'] for l in lines]
    xs = [r[0] for r in line_rects]
    ys = [r[1] for r in line_rects]
    x2s = [r[0] + r[2] for r in line_rects]
    y2s = [r[1] + r[3] for r in line_rects]
    par_rect = (min(xs), min(ys), max(x2s) - min(xs), max(y2s) - min(ys))
    return {
        'text': full_text,
        'par_rect': par_rect,
        'line_rects': line_rects,
        'text_h': float(np.median([line_text_h(l) for l in lines])),
    }


def split_columns(lines):
    """Cluster lines into columns by horizontal overlap; return columns left to right."""
    columns = []   # each: {'x0', 'x1', 'lines'}
    for line in sorted(lines, key=lambda l: l['rect'][0]):
        x, _, w, _ = line['rect']
        for col in columns:
            if horizontal_overlap((x, w), (col['x0'], col['x1'] - col['x0'])) > 0.5:
                col['lines'].append(line)
                col['x0'] = min(col['x0'], x)
                col['x1'] = max(col['x1'], x + w)
                break
        else:
            columns.append({'x0': x, 'x1': x + w, 'lines': [line]})
    columns.sort(key=lambda c: c['x0'])
    return [c['lines'] for c in columns]


def group_lines_to_paragraphs(lines):
    if not lines:
        return []
    avg_height = np.mean([l['rect'][3] for l in lines])
    vertical_threshold = avg_height * 1.2
    horizontal_overlap_threshold = 0.5
    paragraphs = []

    for column in split_columns(lines):
        column = sorted(column, key=lambda l: (l['rect'][1], l['rect'][0]))
        current = []
        for line in column:
            if not current:
                current.append(line)
                continue
            last = current[-1]
            x, y, w, h = line['rect']
            last_x, last_y, last_w, last_h = last['rect']
            gap = y - (last_y + last_h)
            same_par = True
            if 'block' in line and 'block' in last and line.get('strip') == last.get('strip'):
                # Tesseract ids available: a new (block, par) starts a paragraph.
                # Ids of different OCR strips are unrelated: geometry decides there.
                same_par = (line['block'], line['par']) == (last['block'], last['par'])
            hi, lo = sorted((line_text_h(line), line_text_h(last)), reverse=True)
            similar_size = lo <= 0 or hi / lo <= TEXT_H_RATIO   # never merge a heading with body text
            if (same_par and similar_size and gap < vertical_threshold and
                    horizontal_overlap((x, w), (last_x, last_w)) > horizontal_overlap_threshold):
                current.append(line)
            else:
                paragraphs.append(make_paragraph(current))
                current = [line]
        if current:
            paragraphs.append(make_paragraph(current))

    return paragraphs
