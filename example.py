import time
from pumpy import Pump33

p = Pump33("COM5", verbose=False)

""" Test setting mode """
for _ in range(3):
    p.set_mode(p.modes[0])
    p.set_mode(p.modes[1])
    p.set_mode(p.modes[2])

""" Test setting diameter"""
diameters = [0.1, 0.25, 1, 5, 5.233333333, 10, 20.11, 0.123456789]
for x in diameters:
    p.set_diameter(1, x)
    # p.set_diameter(2, x)

""" Test setting flow rate """
# must be in proportional mode to set syringe 2 flow rate directly
p.set_mode("Proportional")
p.set_diameter(1, 1)  # set diameter of syringe 1 to 1mm
p.set_diameter(2, 1)  # set diameter of syringe 2 to 1mm
flow_rates = [0.1, 0.25, 1, 2, 5, 10]  # ul/min
for i in flow_rates:
    p.set_flow_rate(1, i)
    p.set_flow_rate(2, i)
p.set_diameter(1, 50)  # set diameter of syringe 1 to 1mm
p.set_diameter(2, 50)  # set diameter of syringe 2 to 1mm
flow_rates = [10, 100, 1000, 10000]  # ul/min
for i in flow_rates:
    p.set_flow_rate(1, i)
    p.set_flow_rate(2, i)

""" Test setting direction """
for _ in range(3):
    p.set_direction(1, "Reverse")
    p.set_direction(1, "Reverse")
    p.set_direction(1, "Infuse")
    p.set_direction(1, "Refill")

for _ in range(3):
    p.set_direction(2, "Reverse")
    p.set_direction(2, "Reverse")
    p.set_direction(2, "Infuse")
    p.set_direction(2, "Refill")

""" Test running the pump. """
p.set_mode("Proportional")  # set to proportional to control both syringes

p.set_diameter(1, 1)  # set syringe 1 diameter to 1 mm
p.set_flow_rate(1, 70)  # set syringe 1 flow rate to 70 uL/min

for d in ("Infuse", "Refill"):  # infuse for 5 seconds, then refill for 5 seconds
    p.set_direction(1, d)
    p.start()
    time.sleep(5)
    p.stop()

p.set_diameter(1, 20.123)  # set syringe 1 diameter to 20.123 mm
p.set_flow_rate(1, 9876.5)  # set syringe 1 flow rate to 9876.5 uL/min
for d in ("Infuse", "Refill"):  # infuse for 5 seconds, then refill for 5 seconds
    p.set_direction(1, d)
    p.start()
    time.sleep(5)
    p.stop()

p.set_diameter(2, 1)  # set syringe 2 diameter to 1 mm
p.set_flow_rate(2, 70)  # set syringe 2 flow rate to 70 uL/min

for d in ("Infuse", "Refill"):  # infuse for 5 seconds, then refill for 5 seconds
    p.set_direction(1, d)
    p.set_direction(2, d)
    p.start()
    time.sleep(5)
    p.stop()

p.set_diameter(2, 20.123)  # set syringe 2 diameter to 20.123 mm
p.set_flow_rate(2, 9876.5)  # set syringe 2 flow rate to 9876.5 uL/min
for d in ("Infuse", "Refill"):  # infuse for 5 seconds, then refill for 5 seconds
    p.set_direction(1, d)
    p.set_direction(2, d)
    p.start()
    time.sleep(5)
    p.stop()
