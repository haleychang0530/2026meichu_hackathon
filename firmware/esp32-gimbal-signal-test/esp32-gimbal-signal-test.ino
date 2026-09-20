#include <Arduino.h>
#include <ESP32Servo.h>
#include <stdio.h>
#include <string.h>

// GPIO25 = Z 軸左右旋轉；GPIO26 = 鏡頭平台上下仰角。
constexpr int PAN_PIN = 25;
constexpr int TILT_PIN = 26;
constexpr int PAN_MIN = -180;
constexpr int PAN_MAX = 180;
constexpr int TILT_MIN = 0;
constexpr int TILT_MAX = 50;
constexpr int PAN_HOME = 0;
constexpr int TILT_HOME = 25;
constexpr int PAN_TEST = 8;   // 左右各 8 度，最後回到起點。
constexpr int TILT_TEST = 5;  // 上下各 5 度，最後回到起點。

Servo panServo;
Servo tiltServo;
int pan = PAN_HOME;
int tilt = TILT_HOME;
bool movedThisSession = false;

void setAngles(int newPan, int newTilt) {
  pan = constrain(newPan, PAN_MIN, PAN_MAX);
  tilt = constrain(newTilt, TILT_MIN, TILT_MAX);
  // 這是伺服器的邏輯角度到 PWM 脈寬映射；測試只在中心附近移動。
  panServo.writeMicroseconds(map(pan, PAN_MIN, PAN_MAX, 500, 2500));
  tiltServo.writeMicroseconds(map(tilt, TILT_MIN, TILT_MAX, 1250, 1750));
}

void ack(long seq) {
  // 必須維持這個格式，PC 才能辨識 ESP 已收到指令。
  Serial.printf("ACK %ld %d %d\n", seq, pan, tilt);
}

void fourDirectionsOnce() {
  if (movedThisSession) return;
  movedThisSession = true;
  const int originalPan = pan;
  const int originalTilt = tilt;

  setAngles(originalPan + PAN_TEST, originalTilt); delay(300);  // 一側
  setAngles(originalPan, originalTilt); delay(150);
  setAngles(originalPan - PAN_TEST, originalTilt); delay(300);  // 另一側
  setAngles(originalPan, originalTilt); delay(150);
  setAngles(originalPan, originalTilt + TILT_TEST); delay(300); // 一側
  setAngles(originalPan, originalTilt); delay(150);
  setAngles(originalPan, originalTilt - TILT_TEST); delay(300); // 另一側
  setAngles(originalPan, originalTilt); delay(150);
}

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(200);
  panServo.setPeriodHertz(50);
  tiltServo.setPeriodHertz(50);
  panServo.attach(PAN_PIN, 500, 2500);
  tiltServo.attach(TILT_PIN, 1250, 1750);
  setAngles(PAN_HOME, TILT_HOME);
}

void loop() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.isEmpty()) return;

  char command[12] = {};
  long seq = 0;
  long panStep = 0;
  long tiltStep = 0;
  const int fields = sscanf(line.c_str(), "%11s %ld %ld %ld",
                            command, &seq, &panStep, &tiltStep);
  if (fields < 2 || seq < 1) {
    Serial.println("ERR 0 BAD_REQUEST");
    return;
  }

  if (strcmp(command, "PING") == 0) {
    // 網頁每次開始自動對準都會先送 PING；為本次測試重新武裝。
    movedThisSession = false;
    ack(seq);
  } else if (strcmp(command, "TEST") == 0) {
    // 現行網頁在 PING 後送 TEST：四方向只執行一次。
    fourDirectionsOnce();
    ack(seq);
  } else if (strcmp(command, "STEP") == 0 && fields == 4) {
    // 兼容後續網頁調整訊號；尚未收到 TEST 時也會觸發一次。
    // 此測試韌體不依 STEP 追蹤頁面，請勿用於正式閉環。
    fourDirectionsOnce();
    ack(seq);
  } else if (strcmp(command, "STOP") == 0) {
    ack(seq);
  } else {
    Serial.printf("ERR %ld BAD_COMMAND\n", seq);
  }
}
