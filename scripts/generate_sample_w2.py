"""Generate a realistic FAKE W-2 image for testing the vision/upload path.

Writes assets/sample_w2.png and assets/sample_w2.json (ground truth). All data
is fictional — no real PII. Target profile: ~$42,000 single wage earner.
"""

import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(__file__)
ASSETS = os.path.join(HERE, "..", "assets")

GROUND_TRUTH = {
    "employee_name": "Jordan A Rivera",
    "employee_ssn": "123-45-6789",
    "employer_name": "Brightline Coffee Roasters LLC",
    "box1_wages": 42000.00,
    "box2_federal_withholding": 4200.00,
    "box16_state_wages": 42000.00,
    "box17_state_withholding": 1180.00,
}


def _font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),
        "/Library/Fonts/Arial%s.ttf" % (" Bold" if bold else ""),
    ]
    for c in candidates:
        if os.path.exists(c):
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def build():
    W, H = 1000, 640
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f = _font(16)
    fb = _font(16, bold=True)
    fs = _font(12)
    ft = _font(22, bold=True)

    d.text((20, 14), "Form W-2  Wage and Tax Statement", font=ft, fill="black")
    d.text((760, 20), "2025", font=ft, fill="black")

    def box(x, y, w, h, label, value, big=False):
        d.rectangle([x, y, x + w, y + h], outline="black", width=1)
        d.text((x + 6, y + 4), label, font=fs, fill="black")
        d.text((x + 10, y + 22), value, font=(fb if big else f), fill="black")

    # left identity column
    box(20, 60, 460, 70, "a  Employee's social security number", GROUND_TRUTH["employee_ssn"])
    box(20, 130, 460, 70, "b  Employer identification number (EIN)", "84-2719005")
    box(20, 200, 460, 90, "c  Employer's name, address, and ZIP code",
        GROUND_TRUTH["employer_name"])
    d.text((26, 252), "55 Harbor Way, Austin, TX 78701", font=fs, fill="black")
    box(20, 290, 460, 90, "e  Employee's name, address, and ZIP code",
        GROUND_TRUTH["employee_name"])
    d.text((26, 342), "100 Main St, Austin, TX 78701", font=fs, fill="black")

    # right money column
    box(500, 60, 240, 70, "1  Wages, tips, other comp.", "42,000.00", big=True)
    box(745, 60, 235, 70, "2  Federal income tax withheld", "4,200.00", big=True)
    box(500, 130, 240, 70, "3  Social security wages", "42,000.00")
    box(745, 130, 235, 70, "4  Social security tax withheld", "2,604.00")
    box(500, 200, 240, 70, "5  Medicare wages and tips", "42,000.00")
    box(745, 200, 235, 70, "6  Medicare tax withheld", "609.00")
    box(500, 290, 240, 90, "15  State   Employer's state ID", "TX  84-2719005")
    box(745, 290, 235, 45, "16  State wages, tips, etc.", "42,000.00")
    box(745, 335, 235, 45, "17  State income tax", "1,180.00")

    d.text((20, 400), "This is a FAKE W-2 for software testing only. Not a real tax document.",
           font=fs, fill="gray")

    os.makedirs(ASSETS, exist_ok=True)
    img.save(os.path.join(ASSETS, "sample_w2.png"))
    with open(os.path.join(ASSETS, "sample_w2.json"), "w") as fh:
        json.dump(GROUND_TRUTH, fh, indent=2)
    print("wrote assets/sample_w2.png and assets/sample_w2.json")


if __name__ == "__main__":
    build()
