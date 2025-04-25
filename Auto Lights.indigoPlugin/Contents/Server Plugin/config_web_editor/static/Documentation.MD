## Auto Lights Configuration

When opening the plugin’s web editor, you’ll find a section often labeled “Plugin Settings” or “Auto Lights
Configuration.” Here are the key topics:

1. **Global Enable / Disable**  
   A switch or variable that, when false, suspends all Auto Lights logic across every Zone.

2. **Default Lock Durations**
    - **Lock Duration**: The base number of minutes to lock a Zone after a manual change.
    - **Lock Extension**: If presence remains, the lock can extend for additional minutes, preventing auto changes.

3. **Behavior Variables**  
   Used for special global conditions (e.g., “Away Mode” or “House Asleep”). If any condition is triggered, the plugin
   might turn all lights off, overriding normal logic.

---

## Zones

A Zone represents an area or room in your home where Auto Lights controls specific sets of lights
based on presence, time of day, and your configured lighting periods. By grouping devices into Zones,
you can easily manage them as a single unit—turning them on/off or adjusting brightness automatically
when someone enters or leaves a room. Zones also let Auto Lights lock out changes temporarily if you
manually adjust a light, so you keep control for as long as needed.

A Zone typically includes:

- **On Lights**: Devices that auto-lights will turn on under the right conditions (presence, darkness, and an active
  Lighting Period).
- **Off Lights**: Devices the plugin ensures are off if presence stops or if certain conditions are met.
- **Presence Devices**: Motion or other sensors that detect whether someone’s in the Zone.
- **Luminance Devices**: Sensors used to measure ambient light and adjust brightness.
- **Lock Behavior**: Each Zone respects manual overrides. Once locked, the Zone will not automatically turn on or off
  lights until the lock expires, the presence variable goes false, or you reset the lock.

### Advanced Options

- **Exclude from Lock**: If certain devices shouldn’t trigger a manual override lock, add them here.
- **Minimum Luminance**: The threshold below which the plugin considers the space “dark.”

## Presence Devices

> **TIP:** Auto Lights supports the use of the Timed Device plugin. It can be extremely helpful for smoothing out
> intermittent signals or combining multiple inputs into a unified virtual presence device. For example, in a Living
> Room that may lack a dedicated motion sensor, you can create a threshold timer that merges the state of your motion
> sensor with signals from an IP-enabled TV to detect activity.

## Locks

> **NOTE:** Locks do not persist plugin re-starts

* There are Indigo Actions to reset a lock for any given Zone, or all Zones.

---

## Lighting Periods

Lighting Periods let you define windows of time (like “Morning” or “Night”) that set different
behaviors for your lights. Each period has a start and end time, and a mode that describes what
should happen to the lights during that interval—such as turning them on, dimming them, or turning
them off altogether. If you ever notice a manual override (like a person flipping a switch),
Auto Lights respects it until any configured lock duration has passed.

Lighting Periods define the windows of time (with a start and end) during which certain lighting rules apply. In the web
editor:

- **Mode**
    - **On and Off**: Lights can be turned on or off automatically, depending on presence and darkness.
    - **Off Only**: Auto Lights only turns lights off if they’ve been left on or presence disappears.
- **Override Lock Duration**: A specific period can override the default Zone lock duration.
- **Limit Brightness**: Cap the maximum brightness if you don’t want lights going above, say, 50% at night.

---

## Locking, Overrides, and Unlocking

Whenever you manually toggle a device that’s part of a Zone, Auto Lights interprets it as an override. That Zone locks
itself for the configured duration (or an extended time while presence is detected). If you need to restore automation
sooner, use the plugin’s “Reset Lock” actions. Similarly, if a Zone is locked and presence goes away, the plugin can
unlock automatically (depending on settings).

---

# Configuration Backup

Todo: write this.# Auto Lights Documentation

This document takes a deeper look at how Auto Lights orchestrates Zone-based lighting, presence detection,
luminance-based dimming, and time-of-day “Lighting Periods.” While the plugin config is stored in JSON under the hood,
you typically manage it via the built-in web editor. Below are the major concepts you’ll see in that interface.

---

## FAQ & Common Scenarios

1. **I want to disable Auto Lights at bedtime**
    - You can assign a variable (e.g., "Sleep_Mode") as a “Behavior Variable.” If it’s set to true, all Zones can turn
      off. The plugin sees that as a global off condition.

2. **Lights come on too bright or too dim**
    - Check your luminance sensors, or the “Limit Brightness” in the relevant Lighting Period. If it’s set too low or
      not set at all, it might not match your actual preference.

3. **What if I want multiple custom times in one day?**
    - Set up multiple Lighting Periods (e.g., “Morning,” “Day,” “Evening,” “Night”) with different start/stop times and
      brightness caps.

Know that everything here is flexible. If you need to fine-tune advanced JSON or do manual changes, they’re possible,
but generally the web editor is enough for everyday use.

```
