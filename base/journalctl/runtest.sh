#!/usr/bin/bash
# vim: dict+=/usr/share/beakerlib/dictionary.vim cpt=.,w,b,u,t,i,k
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#
#   runtest.sh of /CoreOS/fedoraQA/journalctl-smoke-test
#   Description: Test for journalctl smoke test
#   Author: psklenar@redhat.com <psklenar@redhat.com>
#
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#
#   Copyright (c) 2025 Red Hat, Inc.
#
#   This program is free software: you can redistribute it and/or
#   modify it under the terms of the GNU General Public License as
#   published by the Free Software Foundation, either version 2 of
#   the License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be
#   useful, but WITHOUT ANY WARRANTY; without even the implied
#   warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
#   PURPOSE.  See the GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program. If not, see http://www.gnu.org/licenses/.
#
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# Include Beaker environment
. /usr/share/beakerlib/beakerlib.sh || exit 1


rlJournalStart
    rlPhaseStartSetup
        TESTDIR=$(pwd)
        DEFAULT_IF="$(ip a)"
        rlLog "Arch: $(arch), PC name: $(hostname), $(hostname -A) User: $(whoami)"
        rlLog "$DEFAULT_IF"
    rlPhaseEnd

    rlPhaseStartTest "journalctl -aeb should be empty"
        rlRun "journalctl -aeb"
        rlRun "journalctl -aeb | grep audit"
    rlPhaseEnd

    rlPhaseStartTest "mount points issues"
        if sudo journalctl -b | grep -iv '\<recovery algorithm\>' | grep -iE '\<(dirty bit|corrupt|run fsck|recovery|recovering|tree-log replay)\>' >/dev/null; then
  rlFail "there are some output in recovery algorithm ..."
else
  rlPass "no output"
fi
        journalctl -b > journal.$TMT_REBOOT_COUNT.log
        rlFileSubmit journal.log
        if [ "$TMT_REBOOT_COUNT" -eq 0 ]; then
            rlLog "rebooting"
            tmt-reboot
        fi
        
        if [ "$TMT_REBOOT_COUNT" -eq 1 ]; then
            rlLog "rebooted succesfully"
        fi

    rlPhaseEnd

    rlPhaseStartCleanup
         rlLog 'Cleanup'
    rlPhaseEnd
rlJournalPrintText
rlJournalEnd   
