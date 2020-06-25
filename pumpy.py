import sys
import argparse
import logging
import serial


logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-5.5s]  %(message)s",
)


def _format_float(x):
    """Helper function to convert floats to a fixed width of 6
    characters
    """
    return str(float(x)).ljust(6, "0")[:6]


def _int_to_char(x):
    """Convert 1 to A, 2 to B, etc."""
    return chr(x + 64)


def remove_crud(string):
    """Return string without useless information.

     Return string with trailing zeros after a decimal place, trailing
     decimal points, and leading and trailing spaces removed.
     """
    if "." in string:
        string = string.rstrip("0")

    string = string.lstrip("0 ")
    string = string.rstrip(" .")

    return string


class Chain(serial.Serial):
    """Create Chain object.

    Harvard syringe pumps are daisy chained together in a 'pump chain'
    off a single serial port. A pump address is set on each pump. You
    must first create a chain to which you then add Pump objects.

    Chain is a subclass of serial.Serial. Chain creates a serial.Serial
    instance with the required parameters, flushes input and output
    buffers (found during testing that this fixes a lot of problems) and
    logs creation of the Chain.
    """

    def __init__(self, port, stopbits=serial.STOPBITS_TWO):
        serial.Serial.__init__(
            self, port=port, stopbits=stopbits, parity=serial.PARITY_NONE, timeout=0.1,
        )
        self.flushOutput()
        self.flushInput()
        logging.info("Chain created on %s", port)


class Pump:
    """Create Pump object for Harvard Pump 11.

    Argument:
        Chain: pump chain

    Optional arguments:
        address: pump address. Default is 0.
        name: used in logging. Default is Pump 11.
    """

    def __init__(self, chain, address=0, name="Pump 11"):
        self.name = name
        self.serial = chain
        self.address = "{0:02.0f}".format(address)
        self.diameter = None
        self.flowrate = None
        self.targetvolume = None

        """Query model and version number of firmware to check pump is
        OK. Responds with a load of stuff, but the last three characters
        are XXY, where XX is the address and Y is pump status. :, > or <
        when stopped, running forwards, or running backwards. Confirm
        that the address is correct. This acts as a check to see that
        the pump is connected and working."""
        try:
            self.write("VER")
            resp = self.read(17)

            if int(resp[-3:-1]) != int(self.address):
                raise PumpError("No response from pump at address %s" % self.address)
        except PumpError:
            self.serial.close()
            raise

        logging.info(
            "%s: created at address %s on %s", self.name, self.address, self.serial.port,
        )

    def __repr__(self):
        string = ""
        for attr in self.__dict__:
            string += "%s: %s\n" % (attr, self.__dict__[attr])
        return string

    def write(self, command):
        self.serial.write(self.address + command + "\r")

    def read(self, num_bytes=5):
        response = self.serial.read(num_bytes)

        if len(response) == 0:
            raise PumpError("%s: no response to command" % self.name)
        return response

    def setdiameter(self, diameter):
        """Set syringe diameter (millimetres).

        Pump 11 syringe diameter range is 0.1-35 mm. Note that the pump
        ignores precision greater than 2 decimal places. If more d.p.
        are specificed the diameter will be truncated.
        """
        if diameter > 35 or diameter < 0.1:
            raise PumpError("%s: diameter %s mm is out of range" % (self.name, diameter))

        # TODO: Got to be a better way of doing this with string formatting
        diameter = str(diameter)

        # Pump only considers 2 d.p. - anymore are ignored
        if len(diameter) > 5:
            if diameter[2] == ".":  # e.g. 30.2222222
                diameter = diameter[0:5]
            elif diameter[1] == ".":  # e.g. 3.222222
                diameter = diameter[0:4]

            diameter = remove_crud(diameter)
            logging.warning("%s: diameter truncated to %s mm", self.name, diameter)
        else:
            diameter = remove_crud(diameter)

        # Send command
        self.write("MMD" + diameter)
        resp = self.read(5)

        # Pump replies with address and status (:, < or >)
        if resp[-1] == ":" or resp[-1] == "<" or resp[-1] == ">":
            # check if diameter has been set correctlry
            self.write("DIA")
            resp = self.read(15)
            returned_diameter = remove_crud(resp[3:9])

            # Check diameter was set accurately
            if returned_diameter != diameter:
                logging.error(
                    "%s: set diameter (%s mm) does not match diameter"
                    " returned by pump (%s mm)",
                    self.name,
                    diameter,
                    returned_diameter,
                )
            elif returned_diameter == diameter:
                self.diameter = float(returned_diameter)
                logging.info("%s: diameter set to %s mm", self.name, self.diameter)
        else:
            raise PumpError("%s: unknown response to setdiameter" % self.name)

    def setflowrate(self, flowrate):
        """Set flow rate (microlitres per minute).

        Flow rate is converted to a string. Pump 11 requires it to have
        a maximum field width of 5, e.g. "XXXX." or "X.XXX". Greater
        precision will be truncated.

        The pump will tell you if the specified flow rate is out of
        range. This depends on the syringe diameter. See Pump 11 manual.
        """
        flowrate = str(flowrate)

        if len(flowrate) > 5:
            flowrate = flowrate[0:5]
            flowrate = remove_crud(flowrate)
            logging.warning("%s: flow rate truncated to %s uL/min", self.name, flowrate)
        else:
            flowrate = remove_crud(flowrate)

        self.write("ULM" + flowrate)
        resp = self.read(5)

        if resp[-1] == ":" or resp[-1] == "<" or resp[-1] == ">":
            # Flow rate was sent, check it was set correctly
            self.write("RAT")
            resp = self.read(150)
            returned_flowrate = remove_crud(resp[2:8])

            if returned_flowrate != flowrate:
                logging.error(
                    "%s: set flowrate (%s uL/min) does not match"
                    "flowrate returned by pump (%s uL/min)",
                    self.name,
                    flowrate,
                    returned_flowrate,
                )
            elif returned_flowrate == flowrate:
                self.flowrate = returned_flowrate
                logging.info("%s: flow rate set to %s uL/min", self.name, self.flowrate)
        elif "OOR" in resp:
            raise PumpError(
                "%s: flow rate (%s uL/min) is out of range" % (self.name, flowrate)
            )
        else:
            raise PumpError("%s: unknown response" % self.name)

    def infuse(self):
        """Start infusing pump."""
        self.write("RUN")
        resp = self.read(5)
        while resp[-1] != ">":
            if resp[-1] == "<":  # wrong direction
                self.write("REV")
            else:
                raise PumpError("%s: unknown response to to infuse" % self.name)
            resp = self.serial.read(5)

        logging.info("%s: infusing", self.name)

    def withdraw(self):
        """Start withdrawing pump."""
        self.write("REV")
        resp = self.read(5)

        while resp[-1] != "<":
            if resp[-1] == ":":  # pump not running
                self.write("RUN")
            elif resp[-1] == ">":  # wrong direction
                self.write("REV")
            else:
                raise PumpError("%s: unknown response to withdraw" % self.name)
            resp = self.read(5)

        logging.info("%s: withdrawing", self.name)

    def stop(self):
        """Stop pump."""
        self.write("STP")
        resp = self.read(5)

        if resp[-1] != ":":
            raise PumpError("%s: unexpected response to stop" % self.name)
        logging.info("%s: stopped", self.name)

    def settargetvolume(self, targetvolume):
        """Set the target volume to infuse or withdraw (microlitres)."""
        self.write("MLT" + str(targetvolume))
        resp = self.read(5)

        # response should be CRLFXX:, CRLFXX>, CRLFXX< where XX is address
        # Pump11 replies with leading zeros, e.g. 03, but PHD2000 misbehaves and
        # returns without and gives an extra CR. Use int() to deal with
        if resp[-1] == ":" or resp[-1] == ">" or resp[-1] == "<":
            self.targetvolume = float(targetvolume)
            logging.info("%s: target volume set to %s uL", self.name, self.targetvolume)
        else:
            raise PumpError("%s: target volume not set" % self.name)

    def waituntiltarget(self):
        """Wait until the pump has reached its target volume."""
        logging.info("%s: waiting until target reached", self.name)
        # counter - need it to check if it's the first loop
        i = 0

        while True:
            # Read once
            self.serial.write(self.address + "VOL\r")
            resp1 = self.read(15)

            if ":" in resp1 and i == 0:
                raise PumpError(
                    "%s: not infusing/withdrawing - infuse or "
                    "withdraw first" % self.name
                )
            if ":" in resp1 and i != 0:
                # pump has already come to a halt
                logging.info("%s: target volume reached, stopped", self.name)
                break

            # Read again
            self.serial.write(self.address + "VOL\r")
            resp2 = self.read(15)

            # Check if they're the same - if they are, break, otherwise continue
            if resp1 == resp2:
                logging.info("%s: target volume reached, stopped", self.name)
                break

            i = i + 1


class PHD2000(Pump):
    """Harvard PHD2000 pump object.

    Inherits from Pump class, but needs its own class as it doesn't
    stick to the Pump 11 protocol with commands to stop and set the
    target volume.
    """

    def stop(self):
        """Stop pump."""
        self.write("STP")
        resp = self.read(5)

        if resp[-1] == "*":
            logging.info("%s: stopped", self.name)
        else:
            raise PumpError("%s: unexpected response to stop" % self.name)

    def settargetvolume(self, targetvolume):
        """Set the target volume to infuse or withdraw (microlitres)."""

        # PHD2000 expects target volume in mL not uL like the Pump11, so convert to mL
        targetvolume = str(float(targetvolume) / 1000.0)

        if len(targetvolume) > 5:
            targetvolume = targetvolume[0:5]
            logging.warning(
                "%s: target volume truncated to %s mL", self.name, targetvolume
            )

        self.write("MLT" + targetvolume)
        resp = self.read(5)

        # response should be CRLFXX:, CRLFXX>, CRLFXX< where XX is address
        # Pump11 replies with leading zeros, e.g. 03, but PHD2000 misbehaves and
        # returns without and gives an extra CR. Use int() to deal with
        if resp[-1] == ":" or resp[-1] == ">" or resp[-1] == "<":
            # Been set correctly, so put it back in the object (as uL, not mL)
            self.targetvolume = float(targetvolume) * 1000.0
            logging.info("%s: target volume set to %s uL", self.name, self.targetvolume)


class MightyMini:
    def __init__(self, chain, name="Mighty Mini"):
        self.name = name
        self.serial = chain.serial
        self.flowrate = None
        logging.info("%s: created on %s", self.name, self.serial.port)

    def __repr__(self):
        string = ""
        for attr in self.__dict__:
            string += "%s: %s\n" % (attr, self.__dict__[attr])
        return string

    def setflowrate(self, flowrate):
        flowrate = int(flowrate)
        if flowrate > 9999:
            flowrate = 9999
            logging.warning("%s: flow rate limited to %s uL/min", self.name, flowrate)

        self.serial.write("FM" + "{:04d}".format(flowrate))
        resp = self.serial.read(3)
        self.serial.flushInput()
        if len(resp) == 0:
            raise PumpError("%s: no response to set flowrate" % self.name)
        if resp[0] == "O" and resp[1] == "K":
            # flow rate sent, check it is correct
            self.serial.write("CC")
            resp = self.serial.read(11)
            returned_flowrate = int(float(resp[5:-1]) * 1000)
            if returned_flowrate != flowrate:
                raise PumpError(
                    "%s: set flowrate (%s uL/min) does not match"
                    " flowrate returned by pump (%s uL/min)"
                    % (self.name, flowrate, returned_flowrate)
                )
            if returned_flowrate == flowrate:
                self.flowrate = returned_flowrate
                logging.info("%s: flow rate set to %s uL/min", self.name, self.flowrate)
        else:
            raise PumpError(
                "%s: error setting flow rate (%s uL/min)" % (self.name, flowrate)
            )

    def infuse(self):
        self.serial.write("RU")
        resp = self.serial.read(3)
        if len(resp) == 0:
            raise PumpError("%s: no response to infuse" % self.name)
        if resp[0] == "O" and resp[1] == "K":
            logging.info("%s: infusing", self.name)

    def stop(self):
        self.serial.write("ST")
        resp = self.serial.read(3)
        if len(resp) == 0:
            raise PumpError("%s: no response to stop" % self.name)
        if resp[0] == "O" and resp[1] == "K":
            logging.info("%s: stopping", self.name)


class Pump33:
    """Create Pump object for Harvard Pump 33.

    Argument:
        Chain: pump chain

    Optional arguments:
        address: pump address. Default is 0.
        name: used in logging. Default is Pump 33.
    """

    def __init__(self, port, address=0, name="Pump 33", verbose=False):
        self.name = name
        self.serial = Chain(port)
        self.address = "{0:02.0f}".format(address)
        self.status = None
        self.modes = ["Auto Stop", "Proportional", "Continuous"]
        self.directions = ["Infuse", "Refill", "Reverse"]
        self.direction1 = None
        self.direction2 = None
        self.verbose = verbose

        """Query model and version number of firmware to check pump is
        OK. Responds with a load of stuff, but the last three characters
        are XXY, where XX is the address and Y is pump status. :, > or <
        when stopped, running forwards, or running backwards. Confirm
        that the address is correct. This acts as a check to see that
        the pump is connected and working."""
        try:
            resp = self.write("VER", 11)
            if int(resp[-3:-1]) != int(self.address):
                raise PumpError("No response from pump at address %s" % self.address)
            logging.info(
                "Found pump %s at address %s", resp[1:-4], self.address,
            )
        except PumpError:
            self.serial.close()
            raise
        logging.info(
            "%s: created at address %s on %s", self.name, self.address, self.serial.port,
        )

    def __repr__(self):
        string = ""
        for attr in self.__dict__:
            string += "%s: %s\n" % (attr, self.__dict__[attr])
        return string

    def write(self, command, n=5):
        """Write the specified command, then read back n bytes.

        The last three characters of every response from the pump are
        XXY where XX is the address and Y is the pump status: ':', '>'
        or '<' when stopped, running forwards, or running backwards,
        respectively. This status is always checked to validate the
        response and is stored in self.status.
        """
        self.serial.write(bytes(self.address + command + "\r", encoding="ascii"))
        response_bytes = self.serial.read(n)
        if self.verbose:
            print("\t{} - {}".format(command, response_bytes))
        response = response_bytes.decode()
        if len(response) == 0:
            raise PumpError("%s: No response to command '%s'" % (self.name, command))
        if response[-1] in [":", ">", "<"]:
            self.status = response[-1]
        elif not "OOR" in response:
            raise PumpError(
                "%s: Unknown response '%s' to command '%s'"
                % (self.name, response_bytes, command)
            )
        return response

    def get_status(self):
        """Return the current status. Can be ':', '>' or '<' when
        stopped, running forwards, or running backwards, respectively.
        """
        self.get_mode()  # use to make sure the status is current
        return self.status

    def get_mode(self):
        """Get pump mode.

        Pump 33 has 3 modes: "Auto Stop", "Proportional", and
        "Continuous".
        """
        mode = self.write("MOD", 15)[1:-4]
        for m in self.modes:
            if mode.lower() in m.lower():
                return m
        raise PumpError("%s: get_mode() returned bad mode '%s'" % (self.name, mode))

    def set_mode(self, mode):
        """Set pump mode.

        Pump 33 has 3 modes: "Auto Stop", "Proportional", and
        "Continuous".
        """
        if mode not in self.modes:
            raise PumpError("%s: %s is not a mode name" % (self.name, mode))
        self.write("MOD" + mode[0:3].upper(), 5)
        returned_mode = self.get_mode()
        if returned_mode == mode:
            logging.info("%s: Mode set to %s", self.name, mode)
        else:
            logging.error(
                "%s: Set mode '%s' does not match mode '%s' returned by pump",
                self.name,
                mode,
                returned_mode,
            )

    def _check_syringe_number(self, n):
        """Validate the syringe number. Can only be 1 or 2."""
        if n not in (1, 2):
            raise PumpError(
                "%s: Invalid syringe number '%s'.Must be 1 or 2." % (self.name, n)
            )

    def _check_diameter(self, d):
        """Validate the diameter. Muse be between 0.1 and 50 mm."""
        if d > 50 or d < 0.1:
            raise PumpError("%s: Diameter %s mm is out of range" % (self.name, d))

    def get_diameter(self, syringe_num):
        """Get the set diameter of the specified syringe.

        For the pump, syringe 1 is A and syringe 2 is B.
        """
        self._check_syringe_number(syringe_num)
        return self.write("DIA " + _int_to_char(syringe_num), 15)[1:-4]

    def set_diameter(self, syringe_num, diameter_mm):
        """Set the syringe diameter in millimetres.

        Pump 33 syringe diameter range is 0.1-50 mm.
        """
        self._check_syringe_number(syringe_num)
        self._check_diameter(diameter_mm)
        diameter_mm = _format_float(diameter_mm)
        self.write("DIA " + _int_to_char(syringe_num) + diameter_mm)
        returned_diameter = self.get_diameter(syringe_num)
        if float(diameter_mm) == float(returned_diameter):
            logging.info(
                "%s: Syringe %s diameter set to %s mm",
                self.name,
                syringe_num,
                returned_diameter,
            )
        else:
            logging.error(
                "%s: Syringe %s set diameter '%s mm' does not match "
                "diameter returned by pump '%s mm'",
                self.name,
                syringe_num,
                diameter_mm,
                returned_diameter,
            )

    def get_flow_rate(self, syringe_num):
        """Return the currently set flow rate (uL/min) of the specified
        syringe.
        """
        self._check_syringe_number(syringe_num)
        return remove_crud(self.write("RAT " + _int_to_char(syringe_num), 20)[1:7])

    def set_flow_rate(self, syringe_num, flow_rate):
        """Set both syringe 1 and 2 to the same flow rate (uL/min) in
        Auto Stop and Continuous mode.

        In Proportional mode, it only sets flow rate for syringe 1.
        Syringe 2's flow rate can only be set in Proportional mode.

        The pump will tell you if the specified flow rate is out of
        range. This depends on the syringe diameter. See Pump 33 manual.
        """
        self._check_syringe_number(syringe_num)
        if syringe_num == 2 and self.get_mode() != self.modes[1]:
            raise PumpError(
                "%s: Syringe 2 flow rate can only be set directly in "
                "Proportional mode" % self.name
            )
        flow_rate = _format_float(flow_rate)
        if "OOR" in self.write("RAT " + _int_to_char(syringe_num) + flow_rate + "UM"):
            raise PumpError(
                "%s: Flow rate (%s uL/min) is out of range" % (self.name, flow_rate)
            )
        returned_flowrate = self.get_flow_rate(syringe_num)
        if float(flow_rate) == float(returned_flowrate):
            logging.info(
                "%s: Syringe %s flow rate set to %s uL/min",
                self.name,
                syringe_num,
                returned_flowrate,
            )
        else:
            logging.error(
                "%s: Set flow rate (%s uL/min) does not match flow rate"
                " returned by pump (%s uL/min)",
                self.name,
                flow_rate,
                returned_flowrate,
            )

    def _check_direction(self, direction):
        if direction not in self.directions:
            raise PumpError(
                "%s: Invalid direction '%s'. Can be %s."
                % (self.name, direction, self.directions)
            )

    def _get_other_direction(self, direction):
        """Return the other direction that isn't 'Reverse'. If 'Reverse'
        is supplied, returns 'Infuse'.
        """
        self._check_direction(direction)
        return self.directions[not self.directions.index(direction)]

    def get_direction(self, syringe_num):
        """Return the current direction of the specified syringe.

        Pump 33 has 3 direction settings: Infuse, Refill, and Reverse.

        Syringe 2's direction is only indirectly controlled by setting
        it to be in the same direction as or opposite to syringe 1 using
        parallel or reciprocal linking.
        """
        self._check_syringe_number(syringe_num)
        direction_1 = self.write("DIR", 15)[1:7].capitalize()
        if syringe_num == 1:
            return direction_1
        par = self.write("PAR", 15)[1:-4]
        return direction_1 if par == "ON" else self._get_other_direction(direction_1)

    def set_direction(self, syringe_num, direction):
        """Set syringe direction.

        Pump 33 has 3 direction settings: Infuse, Refill, and Reverse.

        Syringe 2's direction is only indirectly controlled by setting
        it to be in the same direction as or opposite to syringe 1 using
        parallel or reciprocal linking.
        """
        self._check_syringe_number(syringe_num)
        self._check_direction(direction)

        start_direction = self.get_direction(syringe_num)
        if syringe_num == 1:
            if start_direction != direction:
                self.write("DIR REV")  # this will changes both syringes' directions
                self.par()  # change syringe 2 back to it's original direction
        else:
            if direction != start_direction:
                self.par()
            if direction == "Reverse":
                direction = self._get_other_direction(start_direction)

        returned_direction = self.get_direction(syringe_num)
        if direction in ("Reverse", returned_direction):
            logging.info(
                "%s: Syringe %s direction set to '%s'",
                self.name,
                syringe_num,
                returned_direction,
            )
        else:
            logging.error(
                "%s: Set syringe %s direction '%s' does not match"
                " direction returned by pump '%s'",
                self.name,
                syringe_num,
                direction,
                returned_direction,
            )

    def start(self):
        """Start the pump."""
        self.write("RUN", 5)
        logging.info("%s: Started", self.name)

    def stop(self):
        """Stop the pump."""
        self.write("STP", 5)
        logging.info("%s: Stopped", self.name)

    def par(self):
        """Switch the pump between parallel and reciprocal pumping
        direction.

        ON = Parallel (syringes in the same direction)
        OFF = Reciprocal (syringes in the opposite direction)
        """
        states = ["ON", "OFF"]
        original_par = self.write("PAR", 15)[1:-4]
        new_par = states[not states.index(original_par)]
        self.write("PAR " + new_par)
        returned_par = self.write("PAR", 15)[1:-4]
        if returned_par != new_par:
            logging.error("%s: Set Parallel/Reciprocal did not work", self.name)


class PumpError(Exception):
    def __init__(self, msg):
        self.msg = msg
        logging.critical(msg)
        super(PumpError, self).__init__(msg)


# Command line options
# Run with -h flag to see help

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Command line interface to "
        "pumpy module for control of Harvard Pump "
        "11 (default) or PHD2000 syringe pumps, or"
        " SSI Mighty Mini Pump"
    )
    parser.add_argument("port", help="serial port")
    parser.add_argument(
        "address", help="pump address (Harvard pumps)", type=int, nargs="?", default=0
    )
    parser.add_argument("-d", dest="diameter", help="set syringe diameter", type=int)
    parser.add_argument("-f", dest="flowrate", help="set flow rate")
    parser.add_argument("-t", dest="targetvolume", help="set target volume")
    parser.add_argument(
        "-w",
        dest="wait",
        help="wait for target volume to be" " reached; use with -infuse or -withdraw",
        action="store_true",
    )

    # TODO: only allow -w if infuse, withdraw or stop have been specified
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-infuse", action="store_true")
    group.add_argument("-withdraw", action="store_true")
    group.add_argument("-stop", action="store_true")

    pumpgroup = parser.add_mutually_exclusive_group()
    pumpgroup.add_argument("-PHD2000", help="To control PHD2000", action="store_true")
    pumpgroup.add_argument(
        "-MightyMini", help="To control Mighty Mini", action="store_true"
    )
    args = parser.parse_args()

    if args.MightyMini:
        pimp_chain = Chain(args.port, stopbits=serial.STOPBITS_ONE)
    else:
        pimp_chain = Chain(args.port)

    # Command precedence:
    # 1. stop
    # 2. set diameter
    # 3. set flow rate
    # 4. set target
    # 5. infuse|withdraw (+ wait for target volume)

    try:
        if args.PHD2000:
            pump = PHD2000(pimp_chain, args.address, name="PHD2000")
        elif args.MightyMini:
            pump = MightyMini(pimp_chain, name="MightyMini")
        else:
            pump = Pump(pimp_chain, args.address, name="11")

        if args.stop:
            pump.stop()

        if args.diameter:
            pump.setdiameter(args.diameter)

        if args.flowrate:
            pump.setflowrate(args.flowrate)

        if args.targetvolume:
            pump.settargetvolume(args.targetvolume)

        if args.infuse:
            pump.infuse()
            if args.wait:
                pump.waituntiltarget()

        if args.withdraw:
            pump.withdraw()
            if args.wait:
                pump.waituntiltarget()
    finally:
        pimp_chain.close()
