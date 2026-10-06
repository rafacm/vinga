### Fixed

- **An agent no longer reads a browser's MAC address aloud** (#613). A try link names the browser it binds `Browser <MAC>`, and that name read as one a person had chosen, so the agent was told it was speaking through "a device called Browser 02:..." and could say the address to whoever asked which speaker it was. `Browser <mac>` is now a placeholder the server mints exactly as a board's `Device <mac>` is: the agent's prompt leaves it out, a recorded session and its `session_open` event carry no device name for it, and a board swap moves it onto the new address the way it moves a board's.

### Changed

- **`Browser <mac>` is reserved like `Device <mac>`** (#613). `vinga device rename`, `vinga apply` and the configuration API refuse a name of the form `Browser <mac>` for any device whose own MAC it is not, however it is capitalized or spaced, with the same `devices: names of the form ...` refusal the board's spelling already had. A device may still be given either of its own two spellings, which is what keeps an exported document applying back unchanged.

  Upgrade: a device somebody already named in the `Browser <mac>` shape keeps its name, and the agent now treats it as unnamed; rename it with `vinga device rename <mac> <name>` if the agent should say it.
