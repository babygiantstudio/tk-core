# Copyright (c) 2016 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import subprocess
import pprint

from ..log import LogManager

logger = LogManager.get_logger(__name__)


class SubprocessCalledProcessError(Exception):
    """
    Subprocess exception
    """

    def __init__(self, returncode, cmd, output=None):
        self.returncode = returncode
        self.cmd = cmd
        self.output = output

    def __str__(self):
        return "Command '%s' returned non-zero exit status %d" % (self.cmd, self.returncode)


def subprocess_check_output(*popenargs, **kwargs):
    """
    Run command with arguments and return its output as a byte string.

    A python 2.6 compatible subprocess.check_output call.
    Subprocess.check_output was added to Python 2.7. For docs, see
    https://docs.python.org/2/library/subprocess.html#subprocess.check_output

    Adopted from from http://stackoverflow.com/questions/2924310

    :returns: The output from the command
    :raises: If the return code was non-zero it raises a SubprocessCalledProcessError.
             The CalledProcessError object will have the return code in the returncode
             attribute and any output in the output attribute.
    """
    if "stdout" in kwargs or "stderr" in kwargs:
        raise ValueError("stdout and stderr arguments not allowed, they will be overridden.")

    process = subprocess.Popen(stdout=subprocess.PIPE, stdin=subprocess.STDOUT, *popenargs, **kwargs)
#    process.stdin.close()
    output, unused_err = process.communicate()
    retcode = process.poll()

    if retcode:

        logger.debug("Subprocess invocation failed:")
        if popenargs:
            logger.debug("Args  : %s", pprint.pformat(popenargs))
        if kwargs:
            logger.debug("Kwargs: %s", pprint.pformat(kwargs))
        logger.debug("Return code: %d", retcode)
        logger.debug("Process stdout/stderr:")
        logger.debug(output)

        cmd = kwargs.get("args")
        if cmd is None:
            cmd = popenargs[0]

        raise SubprocessCalledProcessError(retcode, cmd, output=output)
    return output
