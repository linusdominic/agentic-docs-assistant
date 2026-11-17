# Troubleshooting

## Notes are not syncing

First check the sync status icon in the bottom-left corner. A grey cloud means the app is offline, an orange cloud means changes are waiting to upload, and a red cloud means sync has failed.

If the cloud is red, open Settings, choose Sync, and select Sync now. If that fails with error code S-401, your session has expired: sign out and sign back in. Error code S-409 means the same note was edited on two devices while offline; see the section on sync conflicts below. Error code S-507 means your account is over its storage limit.

Sync also pauses automatically when the device is in Low Power Mode or on a metered connection. You can change this in Settings under Sync, Network.

## Sync conflicts

When a note is edited on two devices before either has synced, Nimbus Notes keeps both versions. The most recent edit stays in place and the other is saved next to it with "(conflict copy)" added to its title. Compare the two, merge what you need by hand, and delete the copy. Nothing is discarded automatically.

## Recovering deleted notes

Deleted notes move to Trash and stay there for 30 days on every plan. Open Trash from the sidebar, select the note, and choose Restore. After 30 days notes are permanently removed and cannot be recovered by support. On Plus and Team plans you can also restore an earlier version of a note from its History panel for up to 90 days.

## The app is slow or freezes

Notebooks with more than 10,000 notes can slow the desktop app down while the search index rebuilds, which happens after an update or an import. Rebuilding usually takes a few minutes and shows a progress bar in Settings under Advanced. If the app still feels slow afterwards, choose Rebuild search index in the same place, then restart the app.

## I forgot my password

Select Forgot password on the sign-in screen. A reset link is emailed to you and stays valid for one hour. If two-factor authentication is on and you have lost your device, use one of the recovery codes you saved when you set it up. Support cannot turn off two-factor authentication without a recovery code.

## Contacting support

If none of the steps above help, contact support from Help, Contact support inside the app. Include the error code, the app version, and what you were doing when the problem happened. Support replies within one business day on Plus, and within four hours on Team.
