import time

from mini_bdx_runtime.duck_config import DuckConfig
from mini_bdx_runtime.rustypot_position_hwi import HWI

duck_config = DuckConfig()

hwi = HWI(duck_config)
hwi.turn_off()
time.sleep(1)
