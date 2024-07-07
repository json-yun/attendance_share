# python==3.12.2

from flask import Flask, render_template, jsonify, request, redirect, flash, make_response, url_for
from pymongo import MongoClient
import hashlib
import datetime
import jwt
from collections import defaultdict
import threading
import time
import re
from config import Config

client = MongoClient('mongodb://user:password@ip_address/?authSource=admin', port)
db = client.dbjungle
app = Flask(__name__)
app.config.from_object(Config)
SECRET_KEY = app.config['SECRET_KEY']
app.secret_key = SECRET_KEY
CLASSROOM_IP = [IPs]
MAX_STUDYTIME = 3*3600 # seconds
server_time_global = datetime.datetime.now(datetime.UTC)
server_time_timezone4_global = server_time_global + datetime.timedelta(hours=4)
server_time_timezone4_day = server_time_timezone4_global.day
server_time_timezone4_week = server_time_timezone4_global.isocalendar().week

# sha256으로 해시
def hash_password(password):
    hash_object = hashlib.sha256()
    hash_object.update(password.encode("utf-8"))
    return hash_object.hexdigest()

# jwt발급
def issue_token(id):
    expire_hours = 12
    payload = {
        "id": id,
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=expire_hours)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    return token

# 아이디는 알파벳 소문자와 숫자로만 구성되어야 하며, 길이는 5자에서 20자 사이
def is_valid_id(id):
    pattern = r'^[a-z0-9]{5,20}$'
    if re.match(pattern, id):
        return True
    else:
        return False

# 로그인 처리
@app.route("/login", methods=["POST"])
def login():
    id = request.form["userid"].lower()
    password = request.form["password"]
    password = hash_password(password)
    user = db.users.find_one({"id": id}, {"_id": False})
    if not user:
        flash("iderror")
        return render_template("index.html", invalid_id="아이디를 찾을 수 없습니다.")
    
    if user["password"] == password:
        token = issue_token(id)
        response = make_response(redirect(url_for('home')))
        response.set_cookie("mytoken", token)
        return response
    else:
        return render_template("index.html", invalid_password="비밀번호가 다릅니다.")

# 로그아웃 처리
@app.route("/logout")
def logout():
    response = make_response(redirect(url_for('home')))
    response.set_cookie("mytoken", '', expires=0)
    return response

# 로그인페이지
@app.route("/loginpage")
def loginpage():
    token = request.cookies.get("mytoken")
    if authorization(token):
        return redirect(url_for("home"))
    success_message = request.args.get("success_message", "")
    return render_template("index.html", success_message=success_message)

# 회원가입페이지
@app.route("/signup")
def signup():
    return render_template("signup.html")

# 회원가입 처리
@app.route("/signup_post", methods=["POST"])
def signup_post():
    id = request.form["userid"].lower()
    password = request.form["password"]
    password = hash_password(password)
    name = request.form["name"]
    generation = request.form["generation"]
    
    if not is_valid_id(id):
        return render_template("signup.html", error_id="알파벳과 숫자만 사용해야합니다. 길이는 5~20자여야 합니다.")
    if list(db.users.find({"id": id}, {"_id": False})):
        return render_template("signup.html", error_id="아이디가 중복되었습니다.")
    # 이름 띄어쓰기 삭제, 6자제한
    name = "".join(name.split(" "))
    name = name[:6]
    
    user = {"id": id,
            "password": password,
            "name": name,
            "generation": generation,
            "favorite" : [],
            "checkin_time" : 0,
            "checkout_time" : 0,
            "studytime" : 0,
            "medals" : 0,
            "goingout_time" : 0,
            "goingout_duration" : 0,
            "goaltime": 0,
            "studytime_today": 0
            }
    
    db.users.insert_one(user)

    return redirect(url_for("loginpage", success_message="회원가입이 완료되었습니다."))

def check_status(user: defaultdict):
    if user["goingout_time"] and user["checkin_time"] and not user["checkout_time"]:
        status = "goingout"
    elif not user["goingout_time"] and user["checkin_time"] and not user["checkout_time"]:
        status = "checkin"
    elif not user["goingout_time"] and not user["checkin_time"] and not user["checkout_time"]:
        status = "checkout"
    elif not user["goingout_time"] and user["checkin_time"] and user["checkout_time"]:
        status = "checkout"
    else:
        status = "exception"
    
    return status

@app.route("/")
def home():
    user_ip = request.remote_addr
    token = request.cookies.get("mytoken")
    user = authorization(token)
    if user is None:
        return redirect(url_for("loginpage"))
    userlist = listing(token)
    kwargs = request.args
    name = user["name"]
    generation = user["generation"]
    # 입실시간, 퇴실시간, 외출시간 string으로
    if user["checkin_time"]:
        checkin_time = (user["checkin_time"] + datetime.timedelta(hours=9)).strftime("%H:%M:%S")
    else:
        checkin_time = "-"
    if user["checkout_time"]:
        checkout_time = (user["checkout_time"] + datetime.timedelta(hours=9)).strftime("%H:%M:%S")
    else:
        checkout_time = "-"
    if user["goingout_time"]:
        goingout_time = (user["goingout_time"] + datetime.timedelta(hours=9)).strftime("%H:%M:%S")
    else:
        goingout_time = "-"
    
    favorite = user["favorite"]
    studytime = user["studytime"]
    medals = int(user["medals"])
    reason = user["reason"]
    try:
        goaltime = int(user["goaltime"])
        if goaltime < 0:
            goaltime = 0
    except:
        goaltime = 0
    day_left = 7 - server_time_timezone4_global.weekday()
    studytime_today = user["studytime_today"]
    time_left = (goaltime-studytime+studytime_today) /3600
    recommend_hour = round(time_left / day_left, 1)
    if not favorite:
        favorite = []
    if not studytime:
        studytime = 0
    if not recommend_hour:
        recommend_hour = "-"
    if user_ip not in CLASSROOM_IP:
        server_message = "강의실 wifi에 연결되어있어야 합니다."
    else:
        server_message = ""
    
    # 외출: "goingout", 입실: "checkin", 퇴실: "checkout", 예외: "exception"
    status = check_status(user)
        
    return render_template("main.html", 
                            name=name, 
                            generation=generation, 
                            favorite=favorite,
                            checkin_time=checkin_time,
                            checkout_time=checkout_time,
                            goingout_time=goingout_time,
                            userlist=userlist,
                            studytime=round(studytime/3600, 1),
                            in_classroom=in_classroom(user_ip),
                            medals=medals,
                            status=status,
                            reason=reason,
                            recommend_hour=recommend_hour,
                            goaltime=goaltime,
                            server_message=server_message,
                            **kwargs)
    
def authorization(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        userid = payload["id"].lower()
        user = db.users.find_one({"id": userid}, {"_id": False})
        if not user:
            return
        user = defaultdict(float, user)
        return user
    except jwt.ExpiredSignatureError:
        return
    except jwt.exceptions.DecodeError:
        return

def listing(token):
    user = authorization(token)
    if user is not None:
        generation = user["generation"]
        userid = user["id"].lower()
        other_users = list(db.users.find({"id": {"$ne": userid}, "generation": generation}, {"_id": False}))
        order = {"checkin": 0,
                 "goingout": 1,
                 "checkout": 2,
                 "exception": 3}
        other_users.sort(key=lambda u: (order[check_status(defaultdict(float, u))], defaultdict(int, u)["medals"]*-1, u["name"]))
        return other_users
    return

def rank_listing(generation: int):
    users = list(db.users.find({"generation": generation}, {"_id": False}))
    users = [defaultdict(float, user_) for user_ in users]
    users.sort(key=lambda u: u["studytime"], reverse=True)
    users = users[:10]
    users = [i for i in users if i["studytime"] > 0]
    for i in users:
        i["studytime"] = round(i["studytime"]/3600, 1)
    return users

def in_classroom(ip):
    if ip in CLASSROOM_IP:
        return True
    else:
        return False
    
@app.route("/rank")
def rank():
    token = request.cookies.get("mytoken")
    user = authorization(token)
    if user is not None:
        rank_list = rank_listing(user["generation"])
    else:
        return redirect(url_for("loginpage"))
    return render_template("rank.html", rank_list=rank_list)

@app.route("/checkin", methods=["POST"])
def checkin():
    user_ip = request.remote_addr
    now = datetime.datetime.now(datetime.UTC)
    token = request.cookies.get("mytoken")
    user = authorization(token)
    status = check_status(user)
    if user is None:
        return redirect(url_for("loginpage"))
    
    # 강의실ip가 아닌 경우
    if not in_classroom(user_ip):
        if status=="checkin":
            response = make_response(redirect(url_for("home", response_extend="강의실 wifi에서 다시 시도해 주세요.")))
            return response
        else:
            response = make_response(redirect(url_for("home", response_check="강의실 wifi에서 다시 시도해 주세요.")))
            return response
    if user is None:
        response = make_response(redirect(url_for("home", response_check="DB에서 id를 찾을 수 없습니다.")))
        return response
    #입실 중이면 연장 진행
    if status=="checkin":
        result_update, studytime, goingout_duration = update_studytime(now, user)
        if result_update=="success":
            response = make_response(redirect(url_for('home', notification=f"외출 {goingout_duration}시간을 제외,공부시간 {studytime}시간이 저장되었습니다.")))
        elif result_update=="exceeded":
            response = make_response(redirect(url_for('home', response_extend=f"{int(MAX_STUDYTIME/3600)}시간을 초과하였습니다.")))
        else:
            response = make_response(redirect(url_for('home', response_extend="실적을 저장하지 못했습니다.")))
    # 퇴실 상태이면 입실처리
    elif status=="checkout":
        response = make_response(redirect(url_for('home', notification=f"{int(MAX_STUDYTIME/3600)}시간 이내에 연장/퇴실하여야 공부시간이 저장됩니다!")))
    else:
        response = make_response(redirect(url_for('home', response_check="실적을 저장하지 못했습니다.")))
    
    db.users.update_one({"id": user["id"]}, {"$set": {"checkin_time": now,
                                                      "checkout_time": ""}})
    return response

def update_studytime(now: datetime.datetime, user):
    if "checkin_time" in user:
        checkin_time = user["checkin_time"]
        goingout_time = user["goingout_duration"]
        # 퇴실 시
        if "checkout_time" not in user or not user["checkout_time"]:
            # 퇴실시간 기록
            db.users.update_one({"id": user["id"]}, {"$set": {"checkout_time": now,
                                                                "goingout_duration": 0,
                                                                "reason": ""}})
        # 연장 시
        else:
            # 입실시간 갱신
            db.users.update_one({"id": user["id"]}, {"$set": {"checkin_time": now,
                                                                "goingout_duration": 0,
                                                                "reason": ""}})
        
        studytime = now.replace(tzinfo=None) - checkin_time
        studytime = studytime.total_seconds() - goingout_time
        if studytime <= MAX_STUDYTIME:
            if "studytime" in user:
                studytime_before = user["studytime"]
            else:
                studytime_before = 0
            studytime_today_before = user["studytime_today"]
            studytime_new = studytime_before + studytime
            studytime_today_new = studytime_today_before + studytime
            db.users.update_one({"id": user["id"]}, {"$set": {"studytime": studytime_new,
                                                              "studytime_today": studytime_today_new}})
            return "success", round(studytime/3600, 3), round(goingout_time/3600, 3)
        else:
            return "exceeded", -1, 0
    return "error", -1, 0

@app.route("/checkout", methods=["POST"])
def checkout():
    # 강의실 내부 검증
    user_ip = request.remote_addr
    if not in_classroom(user_ip):
        response = make_response(redirect(url_for("home", response_check="강의실 wifi에서 다시 시도해 주세요.")))
        return response
    now = datetime.datetime.now(datetime.UTC)
    token = request.cookies.get("mytoken")
    user = authorization(token)
    if user is None:
        response = make_response(redirect(url_for("home", response_check="DB에서 id를 찾을 수 없습니다.")))
        return response

    # 실적시간 계산
    result, studytime, goingout_duration = update_studytime(now, user)
    if result=="success":
        response = make_response(redirect(url_for('home', notification=f"외출 {goingout_duration}시간을 제외,공부시간 {studytime}시간이 저장되었습니다.")))
        return response
    elif result=="exceeded":
        response = make_response(redirect(url_for("home", response_check=f"{int(MAX_STUDYTIME/3600)}시간을 초과하였습니다.")))
        return response
    else:
        response = make_response(redirect(url_for("home", response_check="실적을 저장하지 못했습니다.")))
        return response

# 외출시간을 db에 저장
@app.route("/goingout", methods=["POST"])
def goingout():
    # 위치검증 및 토큰검증
    user_ip = request.remote_addr
    reason = request.form["reason"]
    if not in_classroom(user_ip):
        response = make_response(redirect(url_for("home", response_goingout="강의실 wifi에서 다시 시도해 주세요.")))
        return response
    now = datetime.datetime.now(datetime.UTC)
    token = request.cookies.get("mytoken")
    user = authorization(token)
    if user is None:
        response = make_response(redirect(url_for("home", response_goingout="DB에서 id를 찾을 수 없습니다.")))
        return response

    # 외출시간이 있으면 외출 종료
    if "goingout_time" in user and user["goingout_time"]:
        goingout_duration = now.replace(tzinfo=None) - user["goingout_time"]
        goingout_duration = goingout_duration.total_seconds()
        if "goingout_duration" in user:
            goingout_duration_before = user["goingout_duration"]
        else:
            goingout_duration_before = 0
        goingout_duration_new = goingout_duration_before + goingout_duration
        db.users.update_one({"id": user["id"]}, {"$set": {"goingout_time": None,
            "goingout_duration": goingout_duration_new,
            "reason": ""}})
        response = make_response(redirect(url_for('home')))
        return response
    # 외출시간이 없으면 외출 처리
    else:
        db.users.update_one({"id": user["id"]}, {"$set": {"goingout_time": now,
                                                          "reason": reason}})
        response = make_response(redirect(url_for('home')))
        return response

@app.route("/favorite", methods=['POST'])
def switchFavor():
    token = request.cookies.get("mytoken")
    user = authorization(token)
    if user is None:
        return redirect(url_for("loginpage"))
    userd = user["id"]
    user_id = request.form.get('userId')
    
    # userd 사용자의 favorite 필드에 user_id 추가
    db.users.update_one(
        {"id": userd},
        {"$addToSet": {"favorite": user_id}}  # $addToSet은 중복된 값이 없으면 추가합니다.
    )

    return redirect(url_for("home"))

@app.route("/favorite_back", methods=['POST'])
def switchFavor_back():
    token = request.cookies.get("mytoken")
    user = authorization(token)
    if user is None:
        return redirect(url_for("loginpage"))
    userd = user["id"]
    user_id = request.form.get('userId')
    
    # userd 사용자의 favorite 필드에 user_id 삭제
    db.users.update_one(
        {"id": userd},
        {"$pull": {"favorite": user_id}}
    )

    return redirect(url_for("home"))

@app.route("/adminpage")
def adminpage():
    token = request.cookies.get("mytoken")
    user = authorization(token)
    if user is not None and user["id"]=="jsyun":
        user_ip = request.remote_addr
        return render_template("admin.html", user_ip=user_ip, server_ip=CLASSROOM_IP)
    else:
        return redirect(url_for("home"))

@app.route("/addip", methods=["POST"])
def addip():
    token = request.cookies.get("mytoken")
    user = authorization(token)
    if user is not None and user["id"]=="jsyun":
        global CLASSROOM_IP
        user_ip = request.remote_addr
        CLASSROOM_IP.append(user_ip)
        return redirect(url_for("adminpage"))
    else:
        return redirect(url_for("home"))

@app.route("/delip", methods=["POST"])
def delip():
    token = request.cookies.get("mytoken")
    user = authorization(token)
    if user is not None and user["id"]=="jsyun":
        global CLASSROOM_IP
        idx = int(request.form["index"])
        CLASSROOM_IP.pop(idx)
        return redirect(url_for("adminpage"))
    else:
        return redirect(url_for("home"))
    
@app.route("/set_goaltime", methods=["POST"])
def set_goaltime():
    token = request.cookies.get("mytoken")
    user = authorization(token)
    if user is None:
        return redirect(url_for("loginpage"))
    userd = user["id"]
    try:
        time = int(request.form["goaltime"])
        db.users.update_one(
            {"id": userd},{"$set":{"goaltime": time}}
        )
    except:
        pass

    return redirect(url_for("home"))

@app.route("/show_goaltime")
def show_goaltime():
    return redirect(url_for("home", show_goaltime=1))

@app.route("/hide_goaltime")
def hide_goaltime():
    return redirect(url_for("home", show_goaltime=0))

if __name__ == "__main__":
    def dbmanager(stop_event):
        def _daily_task(all_users):
            # 오늘의 공부시간 0으로 변경
            db.users.update_many({}, {"$set": {"studytime_today": 0}})
            print("weekly task done at", server_time_global, "utc")
        def _minute_task(all_users):
            # 매 분 3시간 초과한 사람 파악
            for u in all_users:
                status = check_status(u)
                if status=="checkin":
                    duration = server_time_global.replace(tzinfo=None) - u["checkin_time"]
                    duration = duration.total_seconds()
                    duration -= u["goingout_duration"] # 외출시간을 뺀 시간으로 계산
                    if duration > MAX_STUDYTIME:
                        update_studytime(server_time_global, u)
            print("minute task done at", server_time_global, "utc")
        def _weekly_task(all_users):
            # 메달 수여
            generations = []
            for u in all_users:
                generations.append(u["generation"])
            generations = set(generations)
            for gen in generations:
                rank_list = rank_listing(gen)
                if not rank_list:
                    continue
                print(len(rank_list))
                print(min(3, len(rank_list))-1)
                third = rank_list[min(3, len(rank_list))-1]
                third_score = third["studytime"]
                winners = [x for x in rank_list if x["studytime"]>=third_score]
                for winner in winners:
                    id = winner["id"]
                    medals_old = winner["medals"]
                    medals_new = int(medals_old+1)
                    db.users.update_one({"id": id}, {"$set": {"medals": medals_old+1}})
            # 공부시간 0으로 변경
            db.users.update_many({}, {"$set": {"studytime": 0}})
            print("weekly task done at", server_time_global, "utc")
                    
        while True:
            if stop_event.is_set():
                break
            global server_time_global
            global server_time_timezone4_global
            global server_time_timezone4_day
            global server_time_timezone4_week
            all_users = [defaultdict(float, u) for u in db.users.find({}, {"_id": False})]
            # 매분 작업 수행
            # 시간 갱신
            now = datetime.datetime.now(datetime.UTC)
            now_timezone4 = now + datetime.timedelta(hours=9)
            server_time_global = now
            server_time_timezone4_global = now_timezone4
            now_day = now_timezone4.day
            now_week = now_timezone4.isocalendar().week
            if now_week != server_time_timezone4_week:
                # 주차변경 시행
                server_time_timezone4_week = now_week
                _weekly_task(all_users)
            if now_day != server_time_timezone4_day:
                # 일자변경 시행
                server_time_timezone4_day = now_day
                _daily_task(all_users)
                
            _minute_task(all_users)
            time.sleep(60)
    stop_threads = threading.Event()
    thread_dbmanages = threading.Thread(target=dbmanager, args=(stop_threads,))
    thread_dbmanages.start()
    app.run("0.0.0.0", port=5000, debug=True)
    stop_threads.set()
    thread_dbmanages.join()