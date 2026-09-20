#include <Arduino.h>
#include <ESP32Servo.h>
#include <stdio.h>
#include <string.h>

// GPIO25: Z 軸左右旋轉；GPIO26: 鏡頭平台上下仰角。
constexpr int PAN_PIN = 25;
constexpr int TILT_PIN = 26;
constexpr int PAN_MIN = -180;
constexpr int PAN_MAX = 180;
constexpr int TILT_MIN = 0;
constexpr int TILT_MAX = 50;
constexpr int PAN_HOME = 0;
constexpr int TILT_HOME = 25;
constexpr int PAN_WINDOW = 24;
constexpr int TILT_WINDOW = 5;
constexpr int MAX_PAN_STEP = 8;
constexpr int MAX_TILT_STEP = 2;

Servo panServo;
Servo tiltServo;
int pan = PAN_HOME;
int tilt = TILT_HOME;
int startPan = PAN_HOME;
int startTilt = TILT_HOME;
bool active = false;
bool tested = false;

void setAngles(int newPan, int newTilt) {
  pan = constrain(newPan, PAN_MIN, PAN_MAX);
  tilt = constrain(newTilt, TILT_MIN, TILT_MAX);
  // Z 軸實際安裝方向相反：反轉 PWM 映射，邏輯角度與 Serial ACK 不變。
  panServo.writeMicroseconds(map(pan, PAN_MIN, PAN_MAX, 2500, 500));
  tiltServo.writeMicroseconds(map(tilt, TILT_MIN, TILT_MAX, 1250, 1750));
}

void ack(long seq) {
  Serial.printf("ACK %ld %d %d\n", seq, pan, tilt);
}

void error(long seq, const char *reason) {
  Serial.printf("ERR %ld %s\n", seq, reason);
}

void fourDirectionsOnce() {
  if (tested) return;
  tested = true;
  const int originalPan = pan;
  const int originalTilt = tilt;
  setAngles(originalPan + 8, originalTilt); delay(300);
  setAngles(originalPan, originalTilt); delay(150);
  setAngles(originalPan - 8, originalTilt); delay(300);
  setAngles(originalPan, originalTilt); delay(150);
  setAngles(originalPan, originalTilt + 5); delay(300);
  setAngles(originalPan, originalTilt); delay(150);
  setAngles(originalPan, originalTilt - 5); delay(300);
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
  char extra = 0;
  const int fields = sscanf(line.c_str(), "%11s %ld %ld %ld %c",
                            command, &seq, &panStep, &tiltStep, &extra);
  if (fields < 2 || seq < 1 || fields > 4) {
    error(0, "BAD_REQUEST");
    return;
  }

  if (strcmp(command, "PING") == 0 && fields == 2) {
    // 每次開始新一輪對準，先回初始位置並保持 PWM 鎖定。
    setAngles(PAN_HOME, TILT_HOME);
    delay(400);
    active = true;
    tested = false;
    startPan = pan;
    startTilt = tilt;
    ack(seq);
  } else if (strcmp(command, "TEST") == 0 && fields == 2) {
    if (!active) { error(seq, "NOT_STARTED"); return; }
    fourDirectionsOnce();
    ack(seq);
  } else if (strcmp(command, "STEP") == 0 && fields == 4) {
    if (!active) { error(seq, "NOT_STARTED"); return; }
    if (panStep < -MAX_PAN_STEP || panStep > MAX_PAN_STEP ||
        tiltStep < -MAX_TILT_STEP || tiltStep > MAX_TILT_STEP) {
      error(seq, "STEP_LIMIT");
      return;
    }
    const int targetPan = constrain(static_cast<int>(pan + panStep),
                                    max(PAN_MIN, startPan - PAN_WINDOW),
                                    min(PAN_MAX, startPan + PAN_WINDOW));
    const int targetTilt = constrain(static_cast<int>(tilt + tiltStep),
                                     max(TILT_MIN, startTilt - TILT_WINDOW),
                                     min(TILT_MAX, startTilt + TILT_WINDOW));
    setAngles(targetPan, targetTilt);
    delay(120);
    ack(seq);
  } else if (strcmp(command, "STOP") == 0 && fields == 2) {
    active = false;
    ack(seq);
  } else {
    error(seq, "BAD_COMMAND");
  }
}