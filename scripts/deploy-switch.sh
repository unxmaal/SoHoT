#!/bin/bash
# launchd's program for the deploy switch: its command runs as a child of /bin/bash, the program Full Disk Access names. #1516.
"$@"
exit $?
