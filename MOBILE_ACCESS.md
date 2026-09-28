# StudyForge on your phone

## Existing online app

[Open StudyForge](https://lsatprep-fppkbqtqmpdxg7jwlxvnho.streamlit.app/)

This is the existing Streamlit Cloud deployment, recovered from the saved July project conversation and verified on September 27, 2026. Open it from your phone browser on Wi-Fi or cellular data. Your computer does not need to be on.

If Streamlit says the app is asleep, tap **Yes, get this app back up!** and wait for it to load. Sign in with your StudyForge account.

To save it on your phone: in Safari, use Share → Add to Home Screen; in Chrome, use the menu → Add to Home screen.

The hosted app and local desktop app are separate deployments. Local code changes and database updates are not automatically synced to Streamlit Cloud.

## Publish future code changes without chat

Open **StudyForge on this computer** with `Start StudyForge.cmd` and sign in as an admin. Go to **Settings → General → Publish updates to phone link**. The first time, click **Connect GitHub** and finish the browser sign-in. After that, click **Publish update** whenever you want the latest desktop code uploaded to the same online link above. Publishing uses GitHub and Streamlit Cloud; it does not use AI tokens. Allow a minute or two for Streamlit to rebuild, then refresh the phone page.

The button is available only from the local desktop app. The online app cannot read unpublished files on this computer. Publishing uploads app source and styling. It does not upload the local database, uploaded materials, or saved credentials, so study progress and account data are still separate between the desktop and online deployments.

## Local app on home Wi-Fi

1. Connect your phone to the same home Wi-Fi as this computer.
2. Open the phone link emailed to you. Settings → General → Phone access also shows the current link.
3. Sign in with your existing StudyForge account. Your courses and progress use the same database as the desktop app.
4. In Safari, use Share → Add to Home Screen. In Chrome, use the menu → Add to Home screen.

For the local link, the computer must be powered on, awake, and connected to Wi-Fi. Double-click `Start StudyForge.cmd` in this project folder to start it.

Your router can change the computer's IP address. If your saved link stops working, open StudyForge on the computer and copy the current link from Settings. The hostname link in the email may also work on your network.

The local link only works on home Wi-Fi. Use the online app link above for access from other networks.
