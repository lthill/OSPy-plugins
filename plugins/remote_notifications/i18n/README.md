I18N language localisation
====

For translation to other language opening file: ospy_messages.pot in Poedit editor  
https://poedit.net/ and save to your prefered language. Two files (*.mo *.po)  
transfer via email to: martinpihrt@gmail.com for move files  
add to OSPy on my fork on the github.

for generate ospy_messages.pot use: sudo python pygettext.py -a -v -d messages -o plugins/remote_notifications/i18n/ospy_messages.pot plugins/remote_notifications/\*.py plugins/remote_notifications/templates/\*.html 