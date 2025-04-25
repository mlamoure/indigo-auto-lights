# Plugin Settings

This section provides an overview of where you can configure the plugin within Indigo. It covers
general plugin options, how you might enable or disable certain features, and other high-level
choices for setup.

## Indigo Plugin Settings

In the Indigo Plugin Settings, you typically set up how the plugin interacts with Indigo’s internal
resources. The plugin may define references to Indigo variables or devices that it uses behind the
scenes. Usually, you won’t need to configure much manually here, but it’s good to review these
settings to ensure the plugin has the access and permissions it needs.

## Auto Lights Settings

Within Auto Lights Settings, you can fine-tune how the plugin behaves overall. For example, you
might control whether Auto Lights is globally enabled or assign a variable that determines guest
mode. These settings serve as a “master control” for features like lock durations or how the plugin
handles brightness calculations for all your Zones.

# ⏰💡 Lighting Periods 💡⏰

Lighting Periods let you define windows of time (like “Morning” or “Night”) that set different
behaviors for your lights. Each period has a start and end time, and a mode that describes what
should happen to the lights during that interval—such as turning them on, dimming them, or turning
them off altogether. If you ever notice a manual override (like a person flipping a switch),
Auto Lights respects it until any configured lock duration has passed.

# Zones

A Zone represents an area or room in your home where Auto Lights controls specific sets of lights
based on presence, time of day, and your configured lighting periods. By grouping devices into Zones,
you can easily manage them as a single unit—turning them on/off or adjusting brightness automatically
when someone enters or leaves a room. Zones also let Auto Lights lock out changes temporarily if you
manually adjust a light, so you keep control for as long as needed.

## Presence Devices

> **TIP:** Auto Lights supports the use of the Timed Device plugin. It can be extremely helpful for smoothing out
> intermittent signals or combining multiple inputs into a unified virtual presence device. For example, in a Living
> Room
> that may lack a dedicated motion sensor, you can create a threshold timer that merges the state of your motion sensor
> with signals from an IP-enabled TV to detect activity.

## Locks

> **NOTE:** Locks do not persist plugin re-starts

* There are Indigo Actions to reset a lock for any given Zone, or all Zones.
