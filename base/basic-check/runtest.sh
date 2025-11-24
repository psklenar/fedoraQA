#!/usr/bin/bash
# vim: dict+=/usr/share/beakerlib/dictionary.vim cpt=.,w,b,u,t,i,k
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#
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


    rlPhaseStartTest "machine info, install pkg"
        rlRun -t "dmidecode -s system-product-name"
        rlRun -t "rpm -qf /usr/bin/lspci && dnf remove -y pciutils" 0-255
        rlRun -t "dnf install -y pciutils"
        rlRun -t "lspci -nn"
    rlPhaseEnd


    rlPhaseStartTest "os release"
        . /etc/os-release
        rlRun "echo $ID | grep -i fedora"
        rlRun "hostnamectl| grep Linux"
        rlRun "grep '^PRETTY_NAME=' /etc/os-release"
        cat /etc/fedora-release | grep -E '^Fedora release [0-9]+ \(([[:alpha:] ]+)\)$'
        rlAssert0 "fedora release is correct" $?
    rlPhaseEnd

    rlPhaseStartTest "systemctl"
        rlRun "systemctl --all --failed &> failed.log"
        rlRun "grep '0 loaded' failed.log"
    rlPhaseEnd

    rlPhaseStartTest "getenfore"
        rlRun "getenforce | grep Enforcing"
        rlRun "setenforce 0"
        rlRun "getenforce | grep Permissive"
        rlRun "setenforce 1"
        rlRun "getenforce | grep Enforcing"

    rlPhaseEnd

    rlPhaseStartCleanup
         rlLog 'Cleanup'
    rlPhaseEnd
rlJournalPrintText
rlJournalEnd   
