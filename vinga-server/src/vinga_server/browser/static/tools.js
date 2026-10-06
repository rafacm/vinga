// The browser's own device tools, published over MCP as a board
// publishes its own (#613, D3a).
//
// A board is the MCP server on its socket and the conversation server
// its client: the server sends `initialize`, then `tools/list`, then
// `tools/call` whenever its model asks, each a JSON-RPC 2.0 request in
// an `mcp` message, and the board answers each one. This answers the
// same requests the same way, with the tools a browser can honestly
// carry, under the names the firmware gives them so an agent already
// knows them: the speaker's volume, and the status that reports it.
// Nothing a browser cannot do (a screen's brightness, a battery) is
// published.

const PROTOCOL_VERSION = "2024-11-05";

// JSON-RPC's own codes.
const METHOD_NOT_FOUND = -32601;
const INVALID_PARAMS = -32602;

const TOOLS = [
  {
    name: "self.get_device_status",
    description:
      "Provides the real-time information of the device: the volume of its audio speaker and " +
      "whether it is listening. Use this tool for answering questions about the current " +
      "condition (e.g. what is the current volume?), and as the first step to control the " +
      "device (e.g. turn the volume up or down).",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "self.audio_speaker.set_volume",
    description:
      "Set the volume of the audio speaker. If the current volume is unknown, you must call " +
      "`self.get_device_status` tool first and then call this tool.",
    inputSchema: {
      type: "object",
      properties: { volume: { type: "integer", minimum: 0, maximum: 100 } },
      required: ["volume"],
    },
  },
];

function text(value) {
  return { content: [{ type: "text", text: value }], isError: false };
}

// `device` is what the tools reach: `volume()`, `setVolume(n)` and
// `listening()`. Answers the response payload for one request, or null
// for a notification, which gets none.
export function answer(payload, device) {
  if (payload === null || typeof payload !== "object" || payload.id === undefined) {
    return null;
  }
  const reply = (body) => ({ jsonrpc: "2.0", id: payload.id, ...body });
  switch (payload.method) {
    case "initialize":
      return reply({
        result: {
          protocolVersion: PROTOCOL_VERSION,
          capabilities: { tools: {} },
          serverInfo: { name: "vinga-browser", version: "1" },
        },
      });
    case "tools/list":
      return reply({ result: { tools: TOOLS, nextCursor: "" } });
    case "tools/call":
      return reply(call(payload.params || {}, device));
    default:
      return reply({ error: { code: METHOD_NOT_FOUND, message: `Unknown method: ${payload.method}` } });
  }
}

function call(params, device) {
  const args = params.arguments || {};
  switch (params.name) {
    case "self.get_device_status":
      return {
        result: text(
          JSON.stringify({ audio_speaker: { volume: device.volume() }, listening: device.listening() }),
        ),
      };
    case "self.audio_speaker.set_volume": {
      const volume = args.volume;
      if (!Number.isInteger(volume) || volume < 0 || volume > 100) {
        return { error: { code: INVALID_PARAMS, message: "volume must be an integer from 0 to 100" } };
      }
      device.setVolume(volume);
      return { result: text("true") };
    }
    default:
      return { error: { code: METHOD_NOT_FOUND, message: `Unknown tool: ${params.name}` } };
  }
}
