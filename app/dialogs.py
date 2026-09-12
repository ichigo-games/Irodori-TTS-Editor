"""Windows native dialogs in a dedicated UI process (Tk must own its thread)."""
import json
import sys
import tkinter as tk
from tkinter import filedialog


def main():
    request = json.loads(sys.stdin.read())
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    options = {'parent': root, 'title': request['title']}
    if request.get('initialdir'):
        options['initialdir'] = request['initialdir']
    try:
        if request['kind'] == 'folder':
            path = filedialog.askdirectory(**options)
        else:
            options['filetypes'] = ([('台本', '*.txt *.csv')] if request['kind'] == 'script' else
                                    [('WAV音声', '*.wav')] if request['kind'] == 'wav' else
                                    [('Irodoriプロジェクト', '*.irodori')])
            if request['kind'] == 'save':
                options.update(defaultextension='.irodori', initialfile=request.get('name', 'project.irodori'))
                path = filedialog.asksaveasfilename(**options)
            else:
                path = filedialog.askopenfilename(**options)
        print(json.dumps({'path': path}, ensure_ascii=False))
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
