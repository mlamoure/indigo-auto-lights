## Auto Lights Configuration

1. **Global Enable / Disable**  
   A switch or variable that, when false, suspends all Auto Lights logic across every Zone.

2. **Default Lock Durations** : Both of these are the values that will be the default for Zones. If you choose, any Zone
   or Lighting Period can override.
    - **Lock Duration**: The base number of minutes to lock a Zone after a manual change.
    - **Lock Extension**: If presence remains, the lock can extend for additional minutes, preventing auto changes.

3. **Behavior Variables**  
   Used for special global conditions (e.g., “Away Mode” or “House Asleep”). If any condition is triggered, the plugin
   might turn all lights off, overriding normal logic. If you have multiple, these are treated as a "or" condition.

---

## Zones

A Zone represents an area or room in your home where Auto Lights controls specific sets of lights
based on presence, time of day, and your configured lighting periods. A Zone can be a room or a group of rooms such as
an area. You can share presence and luminance devices across multiple rooms, but do not recommend sharing lights.

A Zone typically includes:

- **On / Off Lights**: Devices that auto-lights will control (on and off), turning them on under the right conditions (
  presence,
  darkness, and an active Lighting Period).
    - Supports any device (including plugin devices) that supports .turnOn and .turnOff indigo methods
        - Hue, Hassbridge, and Lutron devices have been thouroughly tested.
    - Support for custom lighting control via plugins: SenseME Fan Lights
- **Off Lights**: Devices that Auto Lights will control only for turning off, if presence stops or if certain conditions
  are met. Auto Lights will never turn these devices on.
    - Note: You do not need to include your On / Off Lights in your Off Lights, but it will not hurt if you do so.
- **Presence Devices**: Motion sensors (can be virtual) that detect whether someone’s in the Zone.
    - Support for any device that has an onState or onOffState properties.

> **TIP:** Auto Lights supports the use of
> kmarkley's [Timed Devices](https://forums.indigodomo.com/viewtopic.php?t=18785) plugin. It can be extremely helpful
> for smoothing out intermittent signals or combining multiple inputs into a unified virtual presence device. For
> example, in a Living Room that may lack a dedicated motion sensor, you can create a threshold timer that merges the
> state of other devices, such as a IP-enabled TV, or nearby doors, to detect activity.

- **Luminance Devices**: Sensors used to measure brightness of the Zone. Once you add a luminance device to your Zone, a
  number of luminance specific options become available in the Zone config. See [below](#luminance-settings) for more
  information on the luminance settings.
- **Locks**: Each Zone respects manual overrides. When this happens, a lock is created for the Zone. Once locked, the
  Zone will not automatically turn on or off lights until the lock expires, the presence variable goes false, or you
  reset the lock. Behavior for locks can be customized and has multiple fields. See [below](#locks) for details.
- **Perform Confirm**: This option is rarely necessary. This option makes Auto Lights wait for confirmation from Indigo
  that the lighting change was implemented sucessfully, before moving to the next task. If you have devices that
  sometimes get out of range, it can be helpful. When this option is not turned on, Auto Lights assumes that Indigo
  delivers the command. This option is not helpful on devices
- **Exclude from Lock**: If certain devices shouldn’t trigger a manual override lock, add them here. I recommend this
  for devices that do long fading times for dimmer changes, like the Hue lights plugin. The transition state will
  confuse Auto Lights and think the dimmer was changed outside of the plugin, and a lock will be created.

## Locks

* Locks are time-based to begin. Once a lock is detected, you will be notified via the Indigo log of the triggering
  event.
* **Lock Duration**: The lock time default is set for the Auto Lights Config. Each Zone can use the default, or
  override. Note that this duration only applies when the lock is first created. Locks can be extended which uses a
  different configuration to determine the amount of time, see fields below.
* **Extend Lock When Presence is Active**: Selecting this option means that the lock will get extended until the lock
  timer expires AND the Zone presence is False before Auto Lights will take back control. Not selecting this option
  means that the lock will expire and then Auto Lights will take back control immediately.
* Once a lock expires, Auto Lights calculates the "target state" of the room and makes those changes. For example, if
  the room is active at the end of a lock expiration, and it's dark, Auto Lights will turn on the on/off lights, and
  turn off the (exclusively) off lights.

> **NOTE:** Locks do not persist plugin re-starts. So, if you restart Auto Lights, it will reset all room lighting to
> the target state.

* **Lock Extension Duration**: Only applicable if 'Extend Lock When Presence is Active' is enabled, if a lock expires
  and the presence is still active, the lock will be extended by this amount.
* There are Indigo Actions to reset a lock for any given Zone, or all Zones.

## Luminance Settings

> **NOTE:** Minimum brightness is only available if a luminance device is added.

Luminance, if provided, is used in a number of ways:

1. If a Zone has presence detected, but the minimum luminance is met (room is brighter than the minimum) then lights
   will NOT be turned on.
2. If the luminance of the Zone changes to be below the minimum luminance while present, then the lights will be turned
   on.
3. **Adjust Dimmer Brightness**: If turned on, the brightness of a dimmer device will be set to:
    - [1 - (current luminance / minimum luminance)] x 100

> **NOTE:** If you provide more than one Luminance device, the current luminance is calculated as the average across all
> sensors.

Setting a minimum brightness:

- **Minimum Luminance**: Minimum luminance can be set via Indigo variable, or statically in the Zone configuration.

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
