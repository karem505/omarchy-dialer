import QtQuick
import Quickshell.Io

// Quickshell has no native file dialog, so shell out to zenity. The chosen
// path is read from stdout; a cancelled dialog exits non-zero and is ignored.
Item {
    id: root
    signal picked(string path)

    function open() {
        proc.running = true;
    }

    Process {
        id: proc
        command: ["zenity", "--file-selection",
                  "--title=Import contacts (.vcf or .csv)",
                  "--file-filter=Contacts | *.vcf *.csv *.VCF *.CSV",
                  "--file-filter=All files | *"]
        stdout: StdioCollector {
            onStreamFinished: {
                const path = text.trim();
                if (path.length > 0) root.picked(path);
            }
        }
    }
}
