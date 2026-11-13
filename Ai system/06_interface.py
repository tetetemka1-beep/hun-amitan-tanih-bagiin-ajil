"""6-р хүн: тусдаа интерфейсийн загвар. Камер/AI/бүртгэл холбоогүй."""
import tkinter as tk
from datetime import datetime

def main():
    root = tk.Tk()
    root.title('Smart Camera — Interface Demo')
    root.geometry('850x550')
    root.configure(bg='#111827')
    tk.Label(root, text='УХААЛАГ КАМЕР | UI DEMO', bg='#111827',
             fg='white', font=('Arial', 20, 'bold')).pack(pady=15)
    clock = tk.Label(root, bg='#111827', fg='#cbd5e1')
    clock.pack()
    tk.Label(root, text='Камерын дүрсний байрлал\n\nЭнэ хувилбарт камер холбогдоогүй',
             bg='#1f2937', fg='#cbd5e1', font=('Arial', 16),
             width=65, height=10).pack(padx=20, pady=15)
    status = tk.Label(root, text='Төлөв: Туршилтын горим', bg='#111827',
                      fg='#93c5fd', font=('Arial', 14))
    status.pack()
    controls = tk.Frame(root, bg='#111827')
    controls.pack(pady=15)
    def show(kind):
        status.config(text='Туршилт: ' + kind,
                      fg='#f87171' if kind == 'Хүн илэрлээ' else '#fbbf24')
    tk.Button(controls, text='Хүний дохио турших', command=lambda: show('Хүн илэрлээ')).pack(side='left', padx=8)
    tk.Button(controls, text='Амьтны дохио турших', command=lambda: show('Амьтан илэрлээ')).pack(side='left', padx=8)
    tk.Button(controls, text='Гарах', command=root.destroy).pack(side='left', padx=8)
    def tick():
        clock.config(text=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        root.after(1000, tick)
    tick()
    root.mainloop()

if __name__ == '__main__':
    main()
