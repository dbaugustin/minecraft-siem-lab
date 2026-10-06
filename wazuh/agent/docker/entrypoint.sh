#!/bin/sh
# Append the lab's localfile blocks once, inside the last <ossec_config>.
if ! grep -q minecraft-siem-lab /var/ossec/etc/ossec.conf; then
  { echo "<ossec_config>"; tr -d '\r' < /tmp/localfile.conf | sed -e '/<!--.*-->/d' -e '/<!--/,/-->/d'; echo "</ossec_config>"; } >> /var/ossec/etc/ossec.conf
fi
/var/ossec/bin/wazuh-control start
exec tail -F /var/ossec/logs/ossec.log
