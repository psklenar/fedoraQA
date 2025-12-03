#!/usr/bin/bash
# vim: dict+=/usr/share/beakerlib/dictionary.vim cpt=.,w,b,u,t,i,k
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#   Author: psklenar@redhat.com <psklenar@redhat.com>
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# Include Beaker environment
. /usr/share/beakerlib/beakerlib.sh || exit 1
PROGRAM="vkcube"


rlJournalStart
    rlPhaseStartSetup
        TESTDIR=$(pwd)
        DEFAULT_IF="$(ip a)"
        rlLog "Arch: $(arch), PC name: $(hostname), $(hostname -A) User: $(whoami)"
        rlLog "$DEFAULT_IF"
        rlRun -t "dmidecode -s system-product-name"
        rlLog "`rpm -qa | grep mesa`"
        VKCUBE_FILE=$(which vkcube)
        rlLog "`rpm -qf $VKCUBE_FILE`"
        CORES_COUNT_OLD=$(coredumpctl list | grep -c "$PROGRAM") &>/dev/null
    rlPhaseEnd

#running vkcube --valide in headless in terminal = https://bugzilla.redhat.com/show_bug.cgi?id=2416951
# this is reproducer for 

    rlPhaseStartTest "check vkcubend about segfaults"
        LOG1=`mktemp`
        #$?=124 is good end by timeout, sigterm
        rlWatchdog "xwfb-run -c mutter -- vkcube --validate" 60
        sleep 5 # it needs some time
        CORES_COUNT_NEW=$(coredumpctl list | grep -c "$PROGRAM") &>/dev/null
        rlAssertEquals "Number of old and new coredumps should be equal." $CORES_COUNT_OLD $CORES_COUNT_NEW
        coredumpctl list
    rlPhaseEnd

    rlPhaseStartCleanup
         rlLog 'no Cleanup'
         rlLog "`ps aux`"
         pkill -9 vkcube
    rlPhaseEnd
rlJournalPrintText
rlJournalEnd   
