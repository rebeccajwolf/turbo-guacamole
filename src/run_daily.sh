#!/bin/bash

# Set up environment variables
export PATH=$PATH:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin:/home/user/.local/bin

# Ensure TZ is set
export TZ=${TZ}

# Change directory to the application directory
cd /home/user/app

# Define the minimum and maximum wait times in seconds
MINWAIT=$((5*60))  # 5 minutes
MAXWAIT=$((20*60)) # 50 minutes

# Calculate a random sleep time within the specified range
SLEEPTIME=$((MINWAIT + RANDOM % (MAXWAIT - MINWAIT)))

# Convert the sleep time to minutes for logging
SLEEP_MINUTES=$((SLEEPTIME / 60))

til(){
  local hour mins target now left initial sleft correction m sec h hm hs ms ss showSeconds toSleep
  showSeconds=true
  [[ $1 =~ ([0-9][0-9]):([0-9][0-9]) ]] || { echo >&2 "USAGE: til HH:MM"; return 1; }
  hour=${BASH_REMATCH[1]} mins=${BASH_REMATCH[2]}
  target=$(date +%s -d "$hour:$mins") || return 1
  now=$(date +%s)
  (( target > now )) || target=$(date +%s -d "tomorrow $hour:$mins")
  left=$((target - now))
  initial=$left
  while (( left > 0 )); do
    if (( initial - left < 300 )) || (( left < 300 )) || [[ ${left: -2} == 00 ]]; then
      # We enter this condition:
      # - once every 5 minutes
      # - every minute for 5 minutes after the start
      # - every minute for 5 minutes before the end
      # Here, we will print how much time is left, and re-synchronize the clock

      hs= ms= ss=
      m=$((left/60)) sec=$((left%60)) # minutes and seconds left
      h=$((m/60)) hm=$((m%60)) # hours and minutes left

      # Re-synchronise
      now=$(date +%s) sleft=$((target - now)) # recalculate time left, multiple 60s sleeps and date calls have some overhead.
      correction=$((sleft-left))
      if (( ${correction#-} > 59 )); then
        echo "System time change detected..."
        (( sleft <= 0 )) && return # terminating as the desired time passed already
        til "$1" && return # resuming the timer anew with the new time
      fi

      # plural calculations
      (( sec > 1 )) && ss=s
      (( hm != 1 )) && ms=s
      (( h > 1 )) && hs=s

      (( h > 0 )) && printf %s "$h hour$hs and "
      (( h > 0 || hm > 0 )) && printf '%2d %s' "$hm" "minute$ms"
      if [[ $showSeconds ]]; then
        showSeconds=
        (( h > 0 || hm > 0 )) && (( sec > 0 )) && printf %s " and "
        (( sec > 0 )) && printf %s "$sec second$ss"
        echo " left..."
        (( sec > 0 )) && sleep "$sec" && left=$((left-sec)) && continue
      else
        echo " left..."
      fi
    fi
    left=$((left-60))
    sleep "$((60+correction))"
    correction=0
  done
}

# Log the sleep duration
echo "Sleeping for $SLEEP_MINUTES minutes ($SLEEPTIME seconds)..."

# Sleep for the calculated time
# sleep $SLEEPTIME
# til $(date -d "$SLEEP_MINUTES minutes" +%H:%M)

# Log the start of the script
echo "Starting script..."

# Execute the Node.js script directly
/home/user/app/.venv/bin/python3 main.py -c config.yaml
