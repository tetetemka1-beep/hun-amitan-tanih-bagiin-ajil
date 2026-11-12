
import cv2
import csv
import os
import time
import winsound
from datetime import datetime
from ultralytics import YOLO

# 1. AI загвар ачаалах
model = YOLO("yolov8n.pt")

# 2. Камер нээх
camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("Камер нээгдсэнгүй!")
    raise SystemExit

# 3. Зураг хадгалах хавтас
folder = "detected_images"
os.makedirs(folder, exist_ok=True)

# 4. CSV бүртгэлийн файл
log_file = "detection_log.csv"

if not os.path.exists(log_file):
    with open(log_file, "w", newline="",
              encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "Date", "Time", "Type",
            "Object", "Confidence", "Image"
        ])

# 5. Таних амьтад
animals = [
    "cat", "dog", "bird", "horse",
    "sheep", "cow", "elephant",
    "bear", "zebra", "giraffe"
]

# 6. Мэдэгдлийн тохиргоо
last_alert = 0
alert_interval = 10  # 10 секунд тутамд

print("Smart AI Camera started")
print("Press Q to quit")

# 7. Камерын үндсэн давталт
while True:

    success, frame = camera.read()

    if not success:
        print("Камерын дүрс уншигдсангүй")
        break

    results = model(frame, verbose=False)

    person_count = 0
    animal_count = 0
    detected_objects = []

    # 8. Объект таних
    for result in results:
        for box in result.boxes:

            cls = int(box.cls[0])
            confidence = float(box.conf[0])
            name = model.names[cls]

            if confidence < 0.5:
                continue

            if name == "person":
                obj_type = "Human"
                label = "HUN"
                color = (0, 255, 0)
                person_count += 1

            elif name in animals:
                obj_type = "Animal"
                label = "AMITAN: " + name
                color = (0, 0, 255)
                animal_count += 1

            else:
                continue

            detected_objects.append(
                (obj_type, name, confidence)
            )

            # 9. Хүрээ зурах
            x1, y1, x2, y2 = map(
                int, box.xyxy[0]
            )

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                color,
                2
            )

            text = f"{label} {confidence:.2f}"

            cv2.putText(
                frame,
                text,
                (x1, max(y1 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2
            )

    # 10. Илэрсэн объектын тоо
    cv2.putText(
        frame,
        f"People: {person_count}",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 0),
        2
    )

    cv2.putText(
        frame,
        f"Animals: {animal_count}",
        (20, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 255),
        2
    )

    # 11. Цаг огноо
    now = datetime.now()

    date_text = now.strftime("%Y-%m-%d")
    time_text = now.strftime("%H:%M:%S")

    cv2.putText(
        frame,
        date_text + " " + time_text,
        (20, 105),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2
    )

    # 12. Анхааруулга
    if detected_objects:

        cv2.putText(
            frame,
            "ALERT: OBJECT DETECTED!",
            (20, 145),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2
        )

        current_time = time.monotonic()

        if current_time - last_alert >= alert_interval:

            last_alert = current_time

            # 13. Зураг хадгалах
            timestamp = now.strftime(
                "%Y%m%d_%H%M%S_%f"
            )

            image_name = f"detection_{timestamp}.jpg"

            image_path = os.path.join(
                folder, image_name
            )

            saved = cv2.imwrite(
                image_path, frame
            )

            if saved:

                # 14. CSV бүртгэл
                with open(
                    log_file,
                    "a",
                    newline="",
                    encoding="utf-8-sig"
                ) as file:

                    writer = csv.writer(file)

                    for obj in detected_objects:

                        obj_type, name, conf = obj

                        writer.writerow([
                            date_text,
                            time_text,
                            obj_type,
                            name,
                            round(conf, 2),
                            image_path
                        ])

                print(
                    f"ALERT! {date_text} {time_text}"
                )

                print(
                    f"People: {person_count}, "
                    f"Animals: {animal_count}"
                )

                print("Saved:", image_path)

            # 15. Дуут мэдэгдэл
            winsound.MessageBeep(
                winsound.MB_ICONEXCLAMATION
            )

    # 16. Камер харуулах
    cv2.imshow("Smart AI Camera", frame)

    # Q дарвал гарах
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# 17. Камер хаах
camera.release()
cv2.destroyAllWindows()

print("Camera stopped")
