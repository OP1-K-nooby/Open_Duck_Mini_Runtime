import argparse
import pickle
import socket
import time
from threading import Thread

from mini_bdx_runtime.imu import Imu

# Rate at which IMU samples are streamed to a connected client, Hz.
SEND_FREQ = 30


class IMUServer:
    def __init__(self, imu=None) -> None:
        self.host = "0.0.0.0"
        self.port = 1234

        self.server_socket = socket.socket()
        self.server_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
        )  # enable address reuse

        self.server_socket.bind((self.host, self.port))

        if imu is None:
            self.imu = Imu(50, upside_down=False)
        else:
            self.imu = imu
        self.stop = False

        Thread(target=self.run, daemon=True).start()

    def run(self) -> None:
        while not self.stop:
            self.server_socket.listen(1)
            conn, address = self.server_socket.accept()  # accept new connection
            print("Connection from: " + str(address))
            try:
                while True:
                    data = self.imu.get_data()
                    data = pickle.dumps(data)
                    conn.send(data)  # send data to the client
                    time.sleep(1 / SEND_FREQ)
            except Exception:
                pass

        self.server_socket.close()
        print("thread closed")
        time.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    imu_server = IMUServer()
    try:
        while True:
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Closing server")
        imu_server.stop = True

    time.sleep(2)
