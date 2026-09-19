#include <Arduino.h>
#include <ESP32Servo.h>
#include <stdlib.h>
#include <string.h>

// GPIO25: Z-axis / left-right pan servo.
// GPIO26: camera platform elevation / up-down tilt servo.
constexpr int PAN_PIN = 25;
constexpr int TILT_PIN = 26;

// Logical travel limits. Check the real servo/gear travel before using the
// full pan range; the demo controller only moves a few degrees from start.
constexpr int PAN_MIN = -180;
constexpr int PAN_MAX = 180;
constexpr int TILT_MIN = 0;
constexpr int TILT_MAX = 50;
constexpr int START_PAN = 0;
constexpr int START_TILT = 25;
constexpr int MAX_STEP = 2;

// Pulse endpoints can be adjusted for the actual servos if needed.
constexpr int PAN_MIN_US = 500;
constexpr int PAN_MAX_US = 2500;
constexpr int TILT_MIN_US = 1250;
constexpr int TILT_MAX_US = 1750;

Servo panServo;
Servo tiltServo;
int panAngle = START_PAN;
int tiltAngle = START_TILT;
char inputLine[80];
size_t inputLength = 0;

void writeAngles(int pan, int tilt) {
  panAngle = constrain(pan, PAN_MIN, PAN_MAX);
  tiltAngle = constrain(tilt, TILT_MIN, TILT_MAX);
  panServo.writeMicroseconds(map(panAngle, PAN_MIN, PAN_MAX, PAN_MIN_US, PAN_MAX_US));
  tiltServo.writeMicroseconds(map(tiltAngle, TILT_MIN, TILT_MAX, TILT_MIN_US, TILT_MAX_US));
}

void ack(long sequence) {
  Serial.printf("ACK %ld %d %d\n", sequence, panAngle, tiltAngle);
}

void fail(long sequence, const char* reason) {
  Serial.printf("ERR %ld %s\n", sequence, reason);
}

bool parseNumber(const char* token, long& result) {
  if (token == nullptr || *token == '\0') return false;
  char* end = nullptr;
  result = strtol(token, &end, 10);
  return end != token && *end == '\0';
}

void testMotion() {
  const int startPan = panAngle;
  const int startTilt = tiltAngle;
  writeAngles(startPan + 4, startTilt); delay(220);
  writeAngles(startPan, startTilt); delay(180);
  writeAngles(startPan - 4, startTilt); delay(220);
  writeAngles(startPan, startTilt); delay(180);
  writeAngles(startPan, startTilt + 4); delay(220);
  writeAngles(startPan, startTilt); delay(180);
  writeAngles(startPan, startTilt - 4); delay(220);
  writeAngles(startPan, startTilt); delay(180);
}

void processLine(char* line) {
  char* command = strtok(line, " ");
  char* sequenceText = strtok(nullptr, " ");
  long sequence = 0;
  if (command == nullptr || !parseNumber(sequenceText, sequence) || sequence < 1) {
    fail(0, "BAD_REQUEST");
    return;
  }

  if (strcmp(command, "PING") == 0 || strcmp(command, "STOP") == 0) {
    if (strtok(nullptr, " ") != nullptr) { fail(sequence, "BAD_REQUEST"); return; }
    ack(sequence);
    return;
  }
  if (strcmp(command, "TEST") == 0) {
    if (strtok(nullptr, " ") != nullptr) { fail(sequence, "BAD_REQUEST"); return; }
    testMotion();
    ack(sequence);
    return;
  }
  if (strcmp(command, "STEP") == 0) {
    long panStep = 0;
    long tiltStep = 0;
    if (!parseNumber(strtok(nullptr, " "), panStep) ||
        !parseNumber(strtok(nullptr, " "), tiltStep) ||
        strtok(nullptr, " ") != nullptr ||
        abs(panStep) > MAX_STEP || abs(tiltStep) > MAX_STEP) {
      fail(sequence, "BAD_STEP");
      return;
    }
    writeAngles(panAngle + static_cast<int>(panStep),
                tiltAngle + static_cast<int>(tiltStep));
    delay(180);
    ack(sequence);
    return;
  }
  fail(sequence, "UNKNOWN_COMMAND");
}

void setup() {
  Serial.begin(115200);
  panServo.setPeriodHertz(50);
  tiltServo.setPeriodHertz(50);
  panServo.attach(PAN_PIN, PAN_MIN_US, PAN_MAX_US);
  tiltServo.attach(TILT_PIN, TILT_MIN_US, TILT_MAX_US);
  writeAngles(START_PAN, START_TILT);
}

void loop() {
  while (Serial.available() > 0) {
    const char incoming = static_cast<char>(Serial.read());
    if (incoming == '\n') {
      inputLine[inputLength] = '\0';
      if (inputLength > 0) processLine(inputLine);
      inputLength = 0;
    } else if (incoming != '\r') {
      if (inputLength + 1 < sizeof(inputLine)) {
        inputLine[inputLength++] = incoming;
      } else {
        inputLength = 0;
        fail(0, "LINE_TOO_LONG");
      }
    }
  }
}
