import 'dart:io';

import 'package:flet/flet.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:path_provider/path_provider.dart';

/// Reads the text on a photo with Google ML Kit, on the phone and offline. ML Kit reads
/// from a file (which also applies the photo's rotation), so the photo is saved first.
class CardReaderService extends FletService {
  CardReaderService({required super.control});

  final TextRecognizer _recognizer = TextRecognizer(script: TextRecognitionScript.latin);

  @override
  void init() {
    super.init();
    control.addInvokeMethodListener(_invokeMethod);
  }

  Future<dynamic> _invokeMethod(String name, dynamic args) async {
    switch (name) {
      case "read_text":
        final bytes = convertToUint8List(args["image"]);
        if (bytes == null) {
          throw Exception("CardReader.read_text needs the photo's bytes");
        }
        final file = File("${(await getTemporaryDirectory()).path}/card_scan.jpg");
        await file.writeAsBytes(bytes, flush: true);
        final result = await _recognizer.processImage(InputImage.fromFilePath(file.path));
        return [
          for (final block in result.blocks)
            for (final line in block.lines)
              {
                "text": line.text,
                "top": line.boundingBox.top,
                "left": line.boundingBox.left,
                "width": line.boundingBox.width,
                "height": line.boundingBox.height,
              }
        ];
      default:
        throw Exception("Unknown CardReader method: $name");
    }
  }

  @override
  void dispose() {
    control.removeInvokeMethodListener(_invokeMethod);
    _recognizer.close();
    super.dispose();
  }
}
