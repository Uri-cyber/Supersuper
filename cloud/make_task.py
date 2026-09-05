# -*- coding: utf-8 -*-
"""
בונה את קובץ המשימה המתוזמנת לפי המחשב הזה.

השם של המשתמש והנתיב לפרויקט נקבעים בזמן ההתקנה ולא נכתבים מראש, כדי
שהתקנה במחשב אחר או בתיקייה אחרת תעבוד בלי לערוך שום קובץ ביד.

הקובץ נכתב ב-UTF-16 עם BOM. זה מה שלוח המשימות של ווינדוס דורש, וקידוד
אחר נדחה בשגיאה לא ברורה.
"""
import io
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE_DIR, "mehiron-daily.xml")

# 09:00 נבחרה לפי מדידה: הרשתות מפרסמות כמעט את כל קובצי המחירים בין חצות
# לשמונה בבוקר. הרצה מוקדמת יותר הייתה מפספסת את מי שמפרסם לקראת הבוקר.
START_HOUR = "09:00:00"

TEMPLATE = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Mehiron - daily price update</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <RandomDelay>PT15M</RandomDelay>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT6H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c "{bat}"</Arguments>
      <WorkingDirectory>{cwd}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def current_user():
    dom = os.environ.get("USERDOMAIN") or os.environ.get("COMPUTERNAME") or ""
    user = os.environ.get("USERNAME") or ""
    return (dom + "\\" + user) if dom else user


def main():
    user = current_user()
    if not user:
        print("לא הצלחתי לזהות את שם המשתמש. המשימה לא נוצרה.")
        return 1
    # התאריך רק קובע את שעת ההתחלה. מחר, כדי שהריצה הראשונה לא תהיה היום.
    import datetime
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    xml = TEMPLATE.format(
        start=f"{tomorrow}T{START_HOUR}",
        user=user,
        bat=os.path.join(BASE_DIR, "daily.bat"),
        cwd=BASE_DIR,
    )
    with io.open(OUT, "w", encoding="utf-16", newline="\r\n") as fh:
        fh.write(xml)
    print(f"נוצר {os.path.basename(OUT)} עבור {user}")
    print(f"  הפרויקט: {os.path.dirname(BASE_DIR)}")
    print(f"  שעה:     {START_HOUR} כל יום")
    return 0


if __name__ == "__main__":
    sys.exit(main())
