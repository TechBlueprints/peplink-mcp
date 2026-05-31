"""InControl 2 typed endpoint helpers (read + IC2-native config writes).

The device-native API proxy (``/rest/o/{org}/g/{grp}/d/{dev}/devapi/{api}``) is
intentionally NOT implemented here — peplink-mcp drives devices directly on the LAN
for native-API calls; IC2 is used only for InControl-managed surfaces.
"""
