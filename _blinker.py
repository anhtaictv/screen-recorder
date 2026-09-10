
import tkinter as tk
root = tk.Tk()
root.geometry("300x100+50+50")
root.attributes("-topmost", True)
lbl = tk.Label(root, text="0", font=("Consolas", 40))
lbl.pack()
counter = [0]
def tick():
    counter[0]+=1
    lbl.config(text=str(counter[0]))
    root.after(16, tick)  # ~60Hz updates
tick()
root.after(4000, root.destroy)
root.mainloop()
