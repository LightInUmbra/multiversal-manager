import 'package:flet/flet.dart';

import 'card_reader.dart';

class Extension extends FletExtension {
  @override
  FletService? createService(Control control) {
    switch (control.type) {
      case "CardReader":
        return CardReaderService(control: control);
      default:
        return null;
    }
  }
}
