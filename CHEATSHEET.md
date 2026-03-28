# Respond.io Automation — Cheatsheet

---

## How to update the script

After you edit `update_usernames.py`, open Terminal and run:

```
cd ~/Downloads && git add update_usernames.py && git commit -m "update script" && git push
```

Done. GitHub will use your new version at the next scheduled run.

---

## How to check the logs

1. Go to: https://github.com/mam-caspi/respond-io-automation/actions
2. Click on the latest run
3. To see what happened: click the **update** job
4. To download the full log file: scroll down to **Artifacts** and click **progress-log-...**

---

## How to pause the schedule

Go to: https://github.com/mam-caspi/respond-io-automation/actions/workflows/update_usernames.yml

Click the **...** menu (top right) → **Disable workflow**

To resume: same place → **Enable workflow**

---

## How to change the schedule time

Open Terminal and run:

```
open ~/Downloads/.github/workflows/update_usernames.yml
```

Find these two lines:

```
- cron: '0 8 * * *'   # 8:00 AM UTC daily
- cron: '0 20 * * *'  # 8:00 PM UTC daily
```

Change the `8` or `20` to any hour you want (0–23, UTC time).
Then save the file and run:

```
cd ~/Downloads && git add .github/workflows/update_usernames.yml && git commit -m "update schedule" && git push
```
