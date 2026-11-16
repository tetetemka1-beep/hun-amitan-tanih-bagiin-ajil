"""3-р хүн: бие даасан AI танилт. Бусад багийн файлыг импортлохгүй."""
import argparse
import cv2
from ultralytics import YOLO

ANIMALS = {'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
           'elephant', 'bear', 'zebra', 'giraffe'}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--model', default='yolov8n.pt')
    parser.add_argument('--conf', type=float, default=0.5)
    args = parser.parse_args()
    if not 0 < args.conf <= 1:
        parser.error('--conf нь 0-ээс их, 1-ээс бага буюу тэнцүү байна.')
    model = YOLO(args.model)
    selected = [i for i, name in model.names.items()
                if name == 'person' or name in ANIMALS]
    if not selected:
        raise RuntimeError('Загварт person/animal ангилал алга.')
    cap = cv2.VideoCapture(args.camera)
    try:
        if not cap.isOpened():
            raise RuntimeError('Камер нээгдсэнгүй.')
        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('Дүрс унших алдаа.')
            result = model.predict(frame, conf=args.conf, classes=selected,
                                   verbose=False)[0]
            cv2.imshow('03 Person and animal detection', result.plot())
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
