# The app's look, on the website and the phone: night-sky purple with gold, a fantasy serif
# (Cinzel) for titles, and the five mana colors as a stripe across the desktop layout's banner.
import flet as ft

TITLE_FONT = "Cinzel"
FONTS = {TITLE_FONT: "https://raw.githubusercontent.com/google/fonts/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf"}

GOLD = "#E0B84F"
BACKGROUND = "#100E1F"
MANA = ["#F3E3A6", "#1F7BC8", "#8E7A99", "#D9453B", "#2E9E5B"]  # W U B R G
COLORS = dict(primary=GOLD, on_primary="#1A1300", primary_container="#4A3B8C",
              on_primary_container="#F3EEFF", secondary="#9D8CFF", on_secondary="#140F33",
              surface="#151229", on_surface="#ECE7FA", on_surface_variant="#A79FC7",
              surface_container_lowest="#0E0C1C", surface_container_low="#1B1733",
              surface_container="#211C3D", surface_container_high="#2A2450",
              surface_container_highest="#332C5E", outline="#5B5288", outline_variant="#2F2A52")


def apply(page):
    title = ft.TextStyle(font_family=TITLE_FONT, weight=ft.FontWeight.W_600, color=COLORS["on_surface"])
    theme = ft.Theme(
        color_scheme=ft.ColorScheme(**COLORS),
        scaffold_bgcolor=BACKGROUND,
        text_theme=ft.TextTheme(title_large=title, headline_small=title),
        appbar_theme=ft.AppBarTheme(bgcolor=COLORS["surface_container"],
                                    title_text_style=ft.TextStyle(font_family=TITLE_FONT, size=20,
                                                                  weight=ft.FontWeight.W_600, color=GOLD)),
        navigation_bar_theme=ft.NavigationBarTheme(bgcolor=COLORS["surface_container"],
                                                   indicator_color=COLORS["primary_container"]),
        data_table_theme=ft.DataTableTheme(heading_row_color=COLORS["surface_container_high"],
                                           heading_text_style=ft.TextStyle(weight=ft.FontWeight.BOLD, color=GOLD)),
        dialog_theme=ft.DialogTheme(bgcolor=COLORS["surface_container"], shape=ft.RoundedRectangleBorder(radius=12)),
        # Messages float as a small rounded card in the app's colors, not a full-width grey bar
        snackbar_theme=ft.SnackBarTheme(behavior=ft.SnackBarBehavior.FLOATING, bgcolor=COLORS["surface_container_highest"],
                                        content_text_style=ft.TextStyle(size=13, color=COLORS["on_surface"]),
                                        shape=ft.RoundedRectangleBorder(radius=10, side=ft.BorderSide(1, COLORS["outline"])),
                                        elevation=6),
    )
    page.fonts = FONTS
    page.theme = page.dark_theme = theme
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BACKGROUND


MUTED = COLORS["on_surface_variant"]
LINE = COLORS["outline_variant"]
GAIN, LOSS = "#4CC38A", "#E5675C"


def gradient(colors, vertical=False):
    return ft.LinearGradient(colors, begin=ft.Alignment.TOP_CENTER if vertical else ft.Alignment.CENTER_LEFT,
                             end=ft.Alignment.BOTTOM_CENTER if vertical else ft.Alignment.CENTER_RIGHT)


def stripe():
    # The five mana colors across the top of the website
    return ft.Container(height=4, gradient=gradient(MANA))


# The website's desktop layout: compact web controls rather than the phone's big touch ones

def button(text, on_click=None, primary=False, url=None, disabled=False):
    style = ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6), padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                           text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_500))
    if primary:
        return ft.FilledButton(text, on_click=on_click, url=url, disabled=disabled, style=style)
    style.side = ft.BorderSide(1, COLORS["outline"])
    style.color = COLORS["on_surface"]
    return ft.OutlinedButton(text, on_click=on_click, url=url, disabled=disabled, style=style)


def panel(content, **options):
    # A rounded, outlined box on the page's background
    return ft.Container(content, bgcolor=COLORS["surface"], border=ft.Border.all(1, LINE), border_radius=10,
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS, **options)


def pill(text, colors=None):
    # A small rounded label, e.g. a card's condition; colors makes it a gradient (foil)
    return ft.Container(ft.Text(text, size=11, color="#1A1300" if colors else MUTED),
                        bgcolor=None if colors else COLORS["surface_container_highest"],
                        gradient=gradient(colors) if colors else None,
                        padding=ft.Padding.symmetric(horizontal=8, vertical=2), border_radius=10)
