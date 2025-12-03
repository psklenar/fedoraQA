#!/usr/bin/bash
# vim: dict+=/usr/share/beakerlib/dictionary.vim cpt=.,w,b,u,t,i,k
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#   Author: psklenar@redhat.com <psklenar@redhat.com>
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# Include Beaker environment
. /usr/share/beakerlib/beakerlib.sh || exit 1


rlJournalStart
    rlPhaseStartSetup
        TESTDIR=$(pwd)
        DEFAULT_IF="$(ip a)"
        rlLog "Arch: $(arch), PC name: $(hostname), $(hostname -A) User: $(whoami)"
        rlLog "$DEFAULT_IF"
        rlRun -t "dmidecode -s system-product-name"
    rlPhaseEnd


    rlPhaseStartTest ""
        LOG1=`mktemp`
        rlRun -s "xwfb-run -c mutter -- timeout --preserve-status 60 vkcube --validate"
        echo "===================="
        cat $rlRun_LOG
        echo "===================="
    rlPhaseEnd


    rlPhaseStartCleanup
         rlLog 'Cleanup'
    rlPhaseEnd
rlJournalPrintText
rlJournalEnd   
