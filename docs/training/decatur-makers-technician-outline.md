# ESB Technician Training Outline

* Only available on WiFi in the space: https://esb.decaturmakers.org:8000/public/
* Documentation - "Help" in top right - http://esb.decaturmakers.org:8000/docs/technicians
* Account creation - staff or I will create an account for you; you'll get a Slack message from EquipmentStatusBoard with your initial password. You have to change this the first time you log in.
  * Staff or I can reset your password if needed.
* ESB has 3 main interfaces:
  1. The web page available on WiFi in the space (or on VPN for staff) - show status
  2. A Slack app/bot - `/esb-status`, `/esb-status Woodshop`
  3. The public status view: https://esb-static.decaturmakers.org (this is a single read-only page on the Internet, updated every time something changes) - show status
* Anyone can report problems with a machine via Slack or (coming soon) scanning a QR code for the machine (must be on WiFi).
  * demo of problem report process via web page http://esb.decaturmakers.org:8000/public/equipment/39
    * statuses - Operational, Degraded, Down
    * safety risk and consumable check boxes
    * resulting Slack post
  * demo of problem report process via Slack (TestB) `/esb-report`
    * resulting Slack post
* Technician web view
  * Demo of login
  * Equipment list - documents/manuals, photos, links, history (show one of the metal machines like the new mill)
  * Kanban board -> repair record
  * Repair queue
  * Claim repair, add notes/photos, set status, resolve
  * Importance of adding notes/photos/etc to help build a knowledge base of common problems
* Technician slack interface `/esb-repair`
  * Mark as duplicate or no issue; claim; update; resolve
* Coming soon
  * Equipment scheduling to replace Skedda, integrated with this
  * RFID-controlled machines Oops button -> repair record
* Documentation - "Help" in top right - http://esb.decaturmakers.org:8000/docs/technicians
* Questions