import cv2
from picamzero import Camera

# Square size the captured frame is resized to, pixels.
CAPTURE_SIZE = (512, 512)
# Where the test capture is written.
CAPTURE_PATH = "/home/bdxv2/aze.jpg"

print("Initializing camera ...")
cam = Camera()
print("Camera initialized")

im = cam.capture_array()
im = cv2.resize(im, CAPTURE_SIZE)
im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)

cv2.imwrite(CAPTURE_PATH, im)
