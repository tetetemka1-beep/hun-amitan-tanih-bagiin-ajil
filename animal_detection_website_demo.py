"""Animal recognition desktop app built with CustomTkinter and YOLOv8."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageOps


APP_TITLE = "Амьтан танигч"
MODEL_NAME = "yolov8n.pt"
IMAGE_TYPES = [("Зургийн файл", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Бүх файл", "*.*")]


class AnimalRecognitionApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1080x720")
        self.minsize(820, 600)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.image_path: Path | None = None
        self.source_image: Image.Image | None = None
        self.preview_image: ctk.CTkImage | None = None
        self.busy = False

        self.configure(fg_color="#0b1220")
        self._build_ui()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=34, pady=(27, 18))
        ctk.CTkLabel(
            header, text="🐾  Амьтан танигч", font=ctk.CTkFont(size=30, weight="bold"),
            text_color="#f3f6fc",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Зургаа оруулаад, доторх амьтдыг хиймэл оюунаар таниулаарай.",
            font=ctk.CTkFont(size=14), text_color="#9aa9c0",
        ).pack(anchor="w", pady=(6, 0))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 28))
        content.grid_columnconfigure((0, 1), weight=1, uniform="panel")
        content.grid_rowconfigure(0, weight=1)

        self.preview_card = ctk.CTkFrame(content, corner_radius=18, fg_color="#121d30")
        self.preview_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.preview_card.grid_columnconfigure(0, weight=1)
        self.preview_card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self.preview_card, text="ЗУРАГ", text_color="#9aa9c0",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=22, pady=(20, 10)
        )

        self.image_label = ctk.CTkLabel(
            self.preview_card, text="📷\n\nТаних зургаа сонгоно уу",
            font=ctk.CTkFont(size=17), text_color="#8494ad",
            fg_color="#0d1727", corner_radius=14,
        )
        self.image_label.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 14))

        image_actions = ctk.CTkFrame(self.preview_card, fg_color="transparent")
        image_actions.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        image_actions.grid_columnconfigure(0, weight=1)
        self.choose_button = ctk.CTkButton(
            image_actions, text="Зураг сонгох", height=42, corner_radius=11,
            font=ctk.CTkFont(size=14, weight="bold"), command=self.choose_image,
        )
        self.choose_button.grid(row=0, column=0, sticky="ew")

        result_card = ctk.CTkFrame(content, corner_radius=18, fg_color="#121d30")
        result_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        result_card.grid_columnconfigure(0, weight=1)
        result_card.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(result_card, text="ТАНИЛТЫН ҮР ДҮН", text_color="#9aa9c0",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=22, pady=(20, 6)
        )
        self.status_label = ctk.CTkLabel(
            result_card, text="Зураг хүлээж байна", anchor="w",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="#f3f6fc",
        )
        self.status_label.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 12))

        self.results_box = ctk.CTkTextbox(
            result_card, corner_radius=12, fg_color="#0d1727", text_color="#d9e3f2",
            font=ctk.CTkFont(size=14), wrap="word",
        )
        self.results_box.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 14))
        self._set_result_text(
            "Энд танилтын хариу гарна.\n\n"
            "YOLOv8 загвар зураг дээрх амьтдыг хайж, төрөл болон итгэлцлийн хувийг харуулна.\n\n"
            "Таних боломжтой: шувуу, муур, нохой, морь, хонь, үхэр, заан, баавгай, тахь, анааш."
        )

        self.detect_button = ctk.CTkButton(
            result_card, text="Амьтан таних", height=44, corner_radius=11,
            font=ctk.CTkFont(size=14, weight="bold"), fg_color="#1e9b78",
            hover_color="#178262", command=self.detect_animals, state="disabled",
        )
        self.detect_button.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 10))
        self.progress = ctk.CTkProgressBar(result_card, mode="indeterminate", height=5)
        self.progress.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 18))
        self.progress.set(0)

    def _set_result_text(self, text: str) -> None:
        self.results_box.configure(state="normal")
        self.results_box.delete("1.0", "end")
        self.results_box.insert("1.0", text)
        self.results_box.configure(state="disabled")

    def choose_image(self) -> None:
        selected = filedialog.askopenfilename(title="Амьтны зураг сонгох", filetypes=IMAGE_TYPES)
        if not selected:
            return
        try:
            image = ImageOps.exif_transpose(Image.open(selected)).convert("RGB")
        except (OSError, ValueError) as error:
            self.status_label.configure(text="Зураг нээж чадсангүй", text_color="#f28b82")
            self._set_result_text(f"Файл уншихад алдаа гарлаа:\n{error}")
            return

        self.image_path = Path(selected)
        self.source_image = image
        self._show_image(image)
        self.status_label.configure(text="Зураг бэлэн боллоо", text_color="#f3f6fc")
        self._set_result_text(f"Сонгосон зураг:\n{self.image_path.name}\n\n«Амьтан таних» товчийг дарна уу.")
        self.detect_button.configure(state="normal")

    def _show_image(self, image: Image.Image) -> None:
        self.preview_image = ctk.CTkImage(light_image=image, dark_image=image, size=(620, 460))
        self.image_label.configure(image=self.preview_image, text="")

    def detect_animals(self) -> None:
        if self.source_image is None or self.busy:
            return
        self.busy = True
        self.detect_button.configure(state="disabled", text="Таних гэж байна…")
        self.choose_button.configure(state="disabled")
        self.status_label.configure(text="Зургийг шинжилж байна…", text_color="#77b8ff")
        self._set_result_text("Загварыг ачаалж, зураг дээрх объектыг шалгаж байна. Анх удаа ажиллуулахад загвар татагдаж болно.")
        self.progress.start()
        image = self.source_image.copy()
        threading.Thread(target=self._run_detection, args=(image,), daemon=True).start()

    def _run_detection(self, image: Image.Image) -> None:
        try:
            from ultralytics import YOLO

            model = YOLO(MODEL_NAME)
            prediction = model.predict(source=image, conf=0.25, verbose=False)[0]
            detections: list[tuple[str, float]] = []
            if prediction.boxes is not None:
                for box in prediction.boxes:
                    class_id = int(box.cls[0].item())
                    confidence = float(box.conf[0].item())
                    detections.append((prediction.names[class_id], confidence))
            rendered = prediction.plot()
            # Ultralytics returns a BGR image; convert it to RGB for Pillow.
            rendered_image = Image.fromarray(rendered[:, :, ::-1].copy())
            self.after(0, self._show_detection_result, rendered_image, detections, None)
        except Exception as error:  # Surface setup and model errors in the app.
            self.after(0, self._show_detection_result, None, [], str(error))

    def _show_detection_result(
        self, image: Image.Image | None, detections: list[tuple[str, float]], error: str | None
    ) -> None:
        self.progress.stop()
        self.progress.set(0)
        self.busy = False
        self.detect_button.configure(state="normal", text="Дахин таних")
        self.choose_button.configure(state="normal")

        if error:
            self.status_label.configure(text="Танилт амжилтгүй", text_color="#f28b82")
            self._set_result_text(
                "Таних үед алдаа гарлаа. Шаардлагатай сангууд суусан эсэх болон интернет холболтоо шалгаарай.\n\n"
                f"Алдааны мэдээлэл:\n{error}"
            )
            return

        if image is not None:
            self._show_image(image)
        if not detections:
            self.status_label.configure(text="Амьтан илэрсэнгүй", text_color="#f3f6fc")
            self._set_result_text(
                "Энэ зургаас таних боломжтой амьтан илэрсэнгүй. Илүү тод, амьтан нь бүтнээрээ харагдсан зураг сонгоод дахин оролдоно уу."
            )
            return

        detections.sort(key=lambda item: item[1], reverse=True)
        self.status_label.configure(text=f"{len(detections)} амьтан илэрлээ", text_color="#72e0b7")
        lines = [f"{index}. {name.title()}  ·  {confidence:.0%} итгэлцэл" for index, (name, confidence) in enumerate(detections, 1)]
        self._set_result_text("Илэрсэн амьтад:\n\n" + "\n".join(lines))


if __name__ == "__main__":
    AnimalRecognitionApp().mainloop()
