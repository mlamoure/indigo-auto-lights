Auto Lights is a lighting automation plugin for the Indigo Home Automation system.

# What does it do?

Auto Lights is an opinionated lighting behavior template for your house. It enables you to set up Lighting Zones, and
configure behavior for each Zone that standardizes the way Indigo controls lights in your home.

I built Auto Lights for myself. My home has a lot of sensors, and almost all Zones / Rooms are controlled by this Auto
Lights program. That is not to say that Auto Lights cannot work for a home with fewer such lights. Doing what Auto
Lights does using Indigo Triggers and Variables requires a lot of manual work. Think of Auto Lights as a template to
remove that complexity from your Indigo setup. This allows you to use your triggers to make finer refinements versus
focusing on the basics of your setup.

The basic functions of Auto Lights is:

* Each Zone has a set of "On / Off Lights", and a set of [presence devices](#presence-devices).
* Each Zone has a set of Lighting Periods, which define based on the time of day whether Auto Lights is the primary for
  turning lights on and off, or just off, for that period.
* When presence is detected in a Zone, and the current Lighting Period indicates Auto Lights is in control of the
  lights, Auto Lights will turn on the lights in the On / Off Lights.
* When presence is not detected, and if there's an active period, Auto Lights will turn off the lights for that Zone.

More advanced features:

* When it's detected that someone changed the lighting state for a Zone, Auto Lights places that Zone in
  a [lock](#locks), so that
  it will not override the change from the user. Locks are time-based, and can be extended based on persistent presence
  until the room is empty again.
* Optionally, a luminance device can be defined, with a minimum luminance setting. So the logic becomes: If Presence
  while Dark -> Turn on the lights.
* For dimmer devices, Auto Lights can optionally set the brightness to a % based on the current luminance level of the
  room. For example: target brightness = (1 - (Current Luminance / Minimum Luminance)) * 100

# Presence Devices

Tip: Auto Lights supports the use of the Timed Device plugin. This can be enourmously helpful to cushion momentary
devices, or combine multiple signals into a virtual presence device. For example, for a Living Room that may or may not
have a motion sensor, you can create a threshhold timer that merges the state of your motion sensor with your TV (
assuming you have a IP-enabled TV that you can use to detect activity or use).

# Lighting Periods

# Locks

# Remaining to do

I built Auto Lights multiple years go as a script prior to turning it into a plugin in 2025. So while the behavior has
been well tested, the conversion to a plugin certainly could introduce bugs.

1. Make luminance devices and minimum luminance levels optional
2. Add validation to the forms for required items
3. Remove any on/off light from the possible list of off lights
4. Documentation, improve tool tips
5. Test locking, reset of locks
6. Improve formatting of info.log() to the indigo event log
7. Add ability for special rules for a Zone or a Lighting Period
8. Clarify plugin setup for use of reflector versus local address for Indigo web server

