import argparse
import contextlib
import pickle
import socket
import time
from queue import Queue
from threading import Thread

import numpy as np
from FramesViewer.viewer import Viewer
from scipy.spatial.transform import Rotation as R

DEFAULT_PORT = 1234
DEFAULT_FREQ = 30
RECV_BUFSIZE = 1024
RECONNECT_DELAY_S = 0.5
QUEUE_SIZE = 1


class IMUClient:
    def __init__(self, host: str, port: int = DEFAULT_PORT, freq: int = DEFAULT_FREQ) -> None:
        self.host = host
        self.port = port
        self.freq = freq
        self.client_socket = socket.socket()
        self.connected = False
        while not self.connected:
            try:
                self.client_socket.connect((self.host, self.port))
                self.connected = True
            except Exception as e:
                print(e)
                time.sleep(RECONNECT_DELAY_S)
        self.imu_queue: Queue = Queue(maxsize=QUEUE_SIZE)
        self.last_imu = [0, 0, 0, 0]

        Thread(target=self.imu_worker, daemon=True).start()

    def imu_worker(self) -> None:
        while True:
            try:
                data = self.client_socket.recv(RECV_BUFSIZE)  # receive response
                data = pickle.loads(data)

                self.imu_queue.put(data)
            except Exception:
                print("missed imu")

            time.sleep(1 / self.freq)

    def get_imu(self):
        with contextlib.suppress(Exception):
            self.last_imu = self.imu_queue.get(False)

        return self.last_imu


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", type=str, required=True, help="IP address of the robot")
    args = parser.parse_args()

    client = IMUClient(args.ip)

    fv = Viewer()
    fv.start()
    pose = np.eye(4)
    pose[:3, 3] = [0.1, 0.1, 0.1]
    try:
        while True:
            quat = client.get_imu()
            try:
                rot_mat = R.from_quat(quat).as_matrix()
                pose[:3, :3] = rot_mat
                fv.pushFrame(pose, "pose")
            except Exception as e:
                print("error", e)
            time.sleep(1 / DEFAULT_FREQ)
    except KeyboardInterrupt:
        pass
