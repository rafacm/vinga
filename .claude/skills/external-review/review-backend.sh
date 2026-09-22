# Shared by run-pr-review.sh and run-plan-review.sh: which reviewer
# runs, at what reasoning effort, and how the run is stamped. Sourced
# with `.`, never executed, so the two scripts cannot drift apart on
# the one decision they share.
#
# review_select reads REVIEW_BACKEND (codex, the default, or claude,
# the quota fallback), REVIEW_MODEL (default gpt-5.6-sol under codex,
# claude-opus-5 under claude) and REVIEW_EFFORT (default high), and
# sets BACKEND, MODEL, EFFORT, PROVIDER and ATTRIBUTION, the last
# being `<provider>/<model>, thinking <level>`, the attribution string
# the implement-issue skill defines. A model from the other backend
# or an effort word outside the backend's vocabulary exits 2 here,
# rather than reaching the reviewer, whose refusal would come back
# looking like a review.
#
# review_run <prompt> <out> <err> runs the reviewer read-only with the
# prompt on stdin, and sets CLI_STAMP (tool, version, enforcement)
# and DURATION (the reviewer's own wall clock, m:ss).
review_select() {
  BACKEND="${REVIEW_BACKEND:-codex}"
  case "$BACKEND" in
    codex)  MODEL="${REVIEW_MODEL:-gpt-5.6-sol}" ;;
    claude) MODEL="${REVIEW_MODEL:-claude-opus-5}" ;;
    *) echo "unknown REVIEW_BACKEND: $BACKEND (codex or claude)" >&2; exit 2 ;;
  esac
  # A REVIEW_MODEL exported for one backend must not silently reach the
  # other (a stale tiering export plus REVIEW_BACKEND=claude would).
  case "$BACKEND:$MODEL" in
    codex:claude-*|claude:gpt-*)
      echo "model $MODEL does not belong to backend $BACKEND" >&2; exit 2 ;;
  esac
  # The effort is pinned rather than left to the backend's default,
  # because a level nothing set is a level nothing can record.
  EFFORT="${REVIEW_EFFORT:-high}"
  case "$BACKEND:$EFFORT" in
    codex:minimal|codex:low|codex:medium|codex:high|codex:xhigh) PROVIDER=openai ;;
    claude:low|claude:medium|claude:high|claude:xhigh|claude:max) PROVIDER=anthropic ;;
    *) echo "effort $EFFORT is not a level backend $BACKEND accepts" >&2; exit 2 ;;
  esac
  ATTRIBUTION="$PROVIDER/$MODEL, thinking $EFFORT"
}

review_run() {
  prompt="$1"; out="$2"; err="$3"
  started="$(date +%s)"
  case "$BACKEND" in
    codex)
      codex exec -m "$MODEL" -c "model_reasoning_effort=$EFFORT" --sandbox read-only - < "$prompt" > "$out" 2> "$err"
      CLI_STAMP="codex CLI $(codex --version | sed 's/codex-cli //'), read-only sandbox"
      ;;
    claude)
      # --allowedTools alone restricts nothing: it adds allow rules and
      # every unlisted tool stays available. The deny list is the fence,
      # and --setting-sources ""/--strict-mcp-config keep local settings
      # and MCP servers from widening it back.
      claude -p --model "$MODEL" --effort "$EFFORT" \
        --strict-mcp-config --setting-sources "" \
        --allowedTools "Read,Glob,Grep" \
        --disallowedTools "Bash,Write,Edit,NotebookEdit,WebFetch,WebSearch,Agent,Task,Workflow,Skill,SendMessage,CronCreate,CronDelete,RemoteTrigger,PushNotification,ScheduleWakeup,EnterWorktree,ExitWorktree,DesignSync,Monitor,LSP,ToolSearch" \
        < "$prompt" > "$out" 2> "$err"
      CLI_STAMP="claude CLI $(claude --version | sed 's/ (Claude Code)//'), read-only tool set"
      ;;
    *) echo "unreachable backend: $BACKEND" >&2; exit 2 ;;
  esac
  elapsed="$(( $(date +%s) - started ))"
  DURATION="$(( elapsed / 60 ))m$(printf '%02d' "$(( elapsed % 60 ))")s"
}
