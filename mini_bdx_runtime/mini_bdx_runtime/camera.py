import base64
import os

import cv2
from picamzero import Camera

# Square size the captured frame is resized to before encoding, pixels.
CAPTURE_SIZE = (512, 512)
# Scratch file the capture is written to before base64-encoding.
CAPTURE_PATH = "/home/bdxv2/aze.jpg"


class Cam:
    def __init__(self) -> None:
        self.cam = Camera()

    def get_encoded_image(self) -> str:
        im = self.cam.capture_array()
        im = cv2.resize(im, CAPTURE_SIZE)
        im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        im = cv2.rotate(im, cv2.ROTATE_90_CLOCKWISE)

        cv2.imwrite(CAPTURE_PATH, im)

        return self.encode_image(CAPTURE_PATH)

    def encode_image(self, image_path: str) -> str:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")
