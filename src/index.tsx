import {
  callable,
  definePlugin,
  toaster,
} from "@decky/api";

import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";

import { useCallback, useEffect, useState } from "react";
import { FaMicrophone, FaMicrophoneSlash, FaSyncAlt } from "react-icons/fa";

const PLUGIN_VERSION = "1.0.3";

interface MicStatus {
  success: boolean;
  error: string | null;
  source: string | null;
  muted: boolean | null;
  version?: string;
}

const getStatus = callable<[], MicStatus>("get_status");
const setMuted = callable<[muted: boolean], MicStatus>("set_muted");
const refresh = callable<[], MicStatus>("refresh");

function Content() {
  const [status, setStatus] = useState<MicStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const result = await getStatus();
      setStatus(result);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus({
        success: false,
        error: message,
        source: null,
        muted: null,
        version: PLUGIN_VERSION,
      });
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const toggleMute = async () => {
    if (status?.muted === null || status?.muted === undefined || busy) {
      return;
    }

    setBusy(true);
    try {
      const result = await setMuted(!status.muted);
      setStatus(result);
      if (result.success) {
        toaster.toast({
          title: result.muted ? "Microphone muted" : "Microphone unmuted",
          body: result.muted
            ? "The Steam Deck internal microphone is now muted."
            : "The Steam Deck internal microphone is now active.",
        });
      } else {
        toaster.toast({
          title: "Microphone error",
          body: result.error ?? "Unable to change microphone state.",
        });
      }
    } catch (error) {
      toaster.toast({
        title: "Microphone error",
        body: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setBusy(false);
    }
  };

  const rediscover = async () => {
    if (busy) {
      return;
    }

    setBusy(true);
    try {
      const result = await refresh();
      setStatus(result);
      if (!result.success) {
        toaster.toast({
          title: "Microphone not found",
          body: result.error ?? "Could not find a microphone input.",
        });
      }
    } catch (error) {
      toaster.toast({
        title: "Detection error",
        body: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setBusy(false);
    }
  };

  const stateText =
    status?.muted === true
      ? "OFF"
      : status?.muted === false
        ? "ON"
        : "UNKNOWN";

  const buttonText =
    status?.muted === true
      ? "Turn Microphone On"
      : "Turn Microphone Off";

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              fontSize: "16px",
              fontWeight: 600,
            }}
          >
            {status?.muted === true ? <FaMicrophoneSlash /> : <FaMicrophone />}
            <span>Microphone: {stateText}</span>
          </div>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={
              busy ||
              !status?.success ||
              status.muted === null ||
              status.muted === undefined
            }
            onClick={() => {
              void toggleMute();
            }}
          >
            {busy ? "Working..." : buttonText}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Detected Device">
        <PanelSectionRow>
          <div
            style={{
              fontSize: "12px",
              opacity: 0.7,
              wordBreak: "break-all",
            }}
          >
            {status?.source ?? "No microphone input detected"}
          </div>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy}
            onClick={() => {
              void rediscover();
            }}
          >
            <FaSyncAlt style={{ marginRight: "8px" }} />
            Re-detect Microphone
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {!status?.success && status?.error && (
        <PanelSection title="Error">
          <PanelSectionRow>
            <div
              style={{
                color: "#ff6b6b",
                fontSize: "12px",
                lineHeight: "1.4",
              }}
            >
              {status.error}
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection>
        <PanelSectionRow>
          <div style={{ fontSize: "11px", opacity: 0.5, textAlign: "center" }}>
            Deck Mic Toggle v{PLUGIN_VERSION}
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  return {
    name: "Deck Mic Toggle",
    titleView: (
      <div className={staticClasses.Title}>
        Deck Mic Toggle
      </div>
    ),
    content: <Content />,
    icon: <FaMicrophone />,
    onDismount() {
      console.log("Deck Mic Toggle unloaded");
    },
  };
});
