#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: (C) 2020-2023 Joel Winarske
#
# SPDX-License-Identifier: Apache-2.0
#
#

import sys

# use kiB's
kb = 1024


def print_banner(text):
    print('*' * (len(text) + 6))
    print("** %s **" % text)
    print('*' * (len(text) + 6))


def handle_ctrl_c(_signal, _frame):
    sys.exit("Ctl+C - Closing")
