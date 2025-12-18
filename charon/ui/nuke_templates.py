def get_final_prep_template():
    return r"""set cut_paste_input [stack 0]
version 16.0 v3
push $cut_paste_input
Group {
 name Projection_Final_Prep
 selected true
 xpos 1054
 ypos 872
}
 BackdropNode {
  inputs 0
  name BackdropNode1
  tile_color 0x8e388e00
  label GEO
  note_font_size 42
  xpos 134
  ypos -187
  bdheight 120
 }
 Input {
  inputs 0
  name geo
  xpos 146
  ypos -113
 }
 set Cb894de00 [stack 0]
 Axis3 {
  inputs 0
  translate {0 143.3999939 0}
  name Target
  xpos 337
  ypos -131
 }
set N668ca00 [stack 0]
push 0
 Camera3 {
  inputs 2
  translate {{CAM_315_TRANS}}
  focal 100
  name Cam315
  xpos 6749
  ypos 82
 }
 Dot {
  name Dot74
  xpos 6773
  ypos 190
 }
 Dot {
  name Dot75
  xpos 6150
  ypos 190
 }
 Dot {
  name Dot76
  xpos 6150
  ypos 303
 }
 Dot {
  name Dot77
  xpos 5780
  ypos 303
 }
 Dot {
  name Dot78
  xpos 5780
  ypos 731
 }
set N2dc66400 [stack 0]
 Dot {
  name Dot79
  xpos 5780
  ypos 796
 }
set N2dc66800 [stack 0]
 Dot {
  name Dot80
  xpos 5780
  ypos 860
 }
push $N668ca00
push 0
 Camera3 {
  inputs 2
  translate {{CAM_INIT_TRANS}}
  focal 100
  name CamInit
  xpos 337
  ypos 69
 }
 Dot {
  name Dot7
  xpos 361
  ypos 174
 }
set Neee4b400 [stack 0]
 Dot {
  name Dot94
  xpos 67
  ypos 174
 }
 Dot {
  name Dot95
  xpos 67
  ypos -528
 }
 Dot {
  name Dot96
  xpos 5950
  ypos -528
 }
 Dot {
  name Dot97
  xpos 5950
  ypos 261
 }
 Dot {
  name Dot93
  xpos 5857
  ypos 261
 }
 Dot {
  name Dot82
  xpos 5857
  ypos 474
 }
set N2dc67400 [stack 0]
 Dot {
  name Dot83
  xpos 5857
  ypos 509
 }
 Constant {
  inputs 0
  channels rgb
  color 1
  name Constant7
  xpos 6537
  ypos 412
 }
 Project3D2 {
  inputs 2
  project_on front
  crop false
  name Project3D13
  xpos 6537
  ypos 506
 }
clone $Cb894de00 {
  xpos 6537
  ypos 575
  selected false
 }
push 0
add_layer {P P.red P.green P.blue P.alpha P.X P.Y P.Z P.x P.y P.z}
add_layer {N N.red N.green N.blue}
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender19
  xpos 6537
  ypos 857
 }
 Invert {
  name Invert7
  xpos 6537
  ypos 988
 }
push $N2dc66800
clone $Cb894de00 {
  inputs 0
  xpos 6194
  ypos 577
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender20
  xpos 6194
  ypos 793
 }
 Dot {
  name Dot84
  xpos 6228
  ypos 931
 }
set Nff59a400 [stack 0]
 FilterErode {
  channels all
  name FilterErode7
  xpos 6427
  ypos 922
 }
 Merge2 {
  inputs 2
  operation multiply
  name Multiply7
  xpos 6427
  ypos 994
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.red 0 0 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.blue 0 2"
  name Shuffle31
  xpos 6427
  ypos 1070
 }
 Grade {
  white 200
  name Grade19
  xpos 6427
  ypos 1168
 }
push $N2dc66400
push $N2dc67400
 Input {
  inputs 0
  name beauty
  xpos 502
  ypos 372
 }
 Dot {
  name Dot81
  xpos 536
  ypos 416
 }
set N19093000 [stack 0]
 Dot {
  name Dot87
  xpos 1452
  ypos 416
 }
set N19093400 [stack 0]
 Dot {
  name Dot88
  xpos 2368
  ypos 416
 }
set N19093800 [stack 0]
 Dot {
  name Dot89
  xpos 3284
  ypos 416
 }
set N19093c00 [stack 0]
 Dot {
  name Dot90
  xpos 4200
  ypos 416
 }
set N1a1ae000 [stack 0]
 Dot {
  name Dot91
  xpos 5116
  ypos 416
 }
set N1a1ae400 [stack 0]
 Dot {
  name Dot92
  xpos 6032
  ypos 416
 }
 Project3D2 {
  inputs 2
  project_on front
  name Project3D14
  xpos 5998
  ypos 471
 }
clone $Cb894de00 {
  xpos 5998
  ypos 578
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel {P.red P.green P.blue}
  N_channel N
  name ScanlineRender21
  xpos 5998
  ypos 728
 }
add_layer {projectionPrev projectionPrev.red projectionPrev.green projectionPrev.blue}
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  out1 projectionPrev
  fromInput2 {
   {0}
   B
  }
  mappings "3 rgba.red 0 0 projectionPrev.red 0 0 rgba.green 0 1 projectionPrev.green 0 1 rgba.blue 0 2 projectionPrev.blue 0 2"
  name Shuffle32
  xpos 5998
  ypos 1152
 }
push $Nff59a400
 Dot {
  name Dot85
  xpos 6118
  ypos 931
 }
 Group {
  name NormalsRotate7
  onCreate "\nn=nuke.thisNode()\nn['mblack'].setFlag(0x0000000000000004)\nn['mgain'].setFlag(0x0000000000000004)\nn['mgamma'].setFlag(0x0000000000000004)\n"
  tile_color 0xff00ff
  xpos 6084
  ypos 1037
  addUserKnob {20 User}
  addUserKnob {41 in l "Normals in" t "Select the layer containing the \nnormals" T Shuffle1.in}
  addUserKnob {41 pick l "Pick Plane" T Plane.pick}
  addUserKnob {22 planereset l Reset -STARTLINE T "nuke.thisNode().knob(\"pick\").setValue(0,0)\nnuke.thisNode().knob(\"pick\").setValue(0,1)\nnuke.thisNode().knob(\"pick\").setValue(1,2)"}
  addUserKnob {26 ""}
  addUserKnob {26 divider_2 l "" +STARTLINE T " "}
  addUserKnob {26 manual l "<b>Manual Rotation</b>" -STARTLINE T "  "}
  addUserKnob {22 rotreset l Reset -STARTLINE T "nuke.thisNode().knob(\"yoffset\").setValue(0)\nnuke.thisNode().knob(\"xzrot\").setValue(0)"}
  addUserKnob {7 yoffset l Horizontal t "Rotate around the world Y axis" R -180 180}
  yoffset {{"degrees(atan2(Cam315.world_matrix.2, Cam315.world_matrix.10))"}}
  addUserKnob {7 xzrot l Vertical t "Rotates around the rotated X axis" R -180 180}
  addUserKnob {26 ""}
  addUserKnob {26 matte l "@b;Matte Output" T "      "}
  addUserKnob {6 inv l "Invert    " t "This happens before the matte \ntweaks" -STARTLINE}
  addUserKnob {6 amask l "Mask by Alpha    " -STARTLINE}
  addUserKnob {6 unpre l Unpremult -STARTLINE}
  addUserKnob {7 exp l Exponent t "Exponential falloff" R 1 10}
  exp 2
  addUserKnob {22 expreset l Reset -STARTLINE T "nuke.thisNode().knob(\"exp\").setValue(2)"}
  addUserKnob {7 mblack l Black R -1 1}
  addUserKnob {22 mblackreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mblack\").setValue(0)"}
  addUserKnob {7 mgain l White R 0 4}
  mgain 1
  addUserKnob {22 mgainreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgain\").setValue(1)"}
  addUserKnob {7 mgamma l Gamma R 0 4}
  mgamma 1
  addUserKnob {22 mgammareset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgamma\").setValue(1)"}
  addUserKnob {26 ""}
  addUserKnob {26 "" l mask T ""}
  addUserKnob {41 maskChannelInput l "" -STARTLINE T Merge1.maskChannelInput}
  addUserKnob {41 inject -STARTLINE T Merge1.inject}
  addUserKnob {41 invert_mask l invert -STARTLINE T Merge1.invert_mask}
  addUserKnob {41 fringe -STARTLINE T Merge1.fringe}
  addUserKnob {41 mix T Merge1.mix}
  addUserKnob {20 info l Info}
  addUserKnob {26 infotext l "" +STARTLINE T "W_SuperNormal generates a surface angle based matte using normals.\n\n1. Select the layer containing normals in the dropdown menu.\n2. Enable color picker and pick the point where you want the matte to be white.\n  (I look at the alpha output, hold ctrl+alt and \"glide\" over the surfaces.)\n3. You can also manually rotate the matte. When you colorpick a new point,\n  it is recommended that you reset the manual rotation values to 0.\n"}
  addUserKnob {20 v2_1_group l "v2.1 - Feb 2019" n 1}
  v2_1_group 0
  addUserKnob {26 v2_1_text l "" +STARTLINE T "  -Manual rotation working as originally envisioned: It is more intuitive \n   and faster to reach any desired angle with horizontal(Y) and vertical\n   rotation than with separate XYZ rotations.\n  -General cleanup & refinements.\n"}
  addUserKnob {20 endGroup n -1}
  addUserKnob {20 v2group l "v2.0 - 2018" n 1}
  v2group 0
  addUserKnob {26 v2text l "" +STARTLINE T "  -Adopted a different method for rotating normals shown to me by Daniel Pelc\n  -Simpler math for converting normals into a matte with the help of Erwan Leroy\n"}
  addUserKnob {20 endGroup_1 l endGroup n -1}
  addUserKnob {26 v1_1_text l "" +STARTLINE T "    v1.1 - 2016"}
  addUserKnob {26 ""}
  addUserKnob {26 spacer_1 l "" +STARTLINE T "     "}
  addUserKnob {26 copyright l "&#169;  Wes Heo" -STARTLINE T " "}
 }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.yoffset} 0}
   name Axis10
   label H
   xpos -173
   ypos -163
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {{parent.xzrot} {-degrees(parent.Plane.picked.g)} 0}
   name Axis2
   label V
   xpos -171
   ypos -62
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.Axis2.rotate.y} 0}
   name Axis5
   label V
   xpos -170
   ypos 34
  }
  Input {
   inputs 0
   name Inputmask
   xpos 132
   ypos 544
   number 1
  }
  Input {
   inputs 0
   name N
   xpos 0
   ypos -425
  }
  Shuffle {
   in N
   alpha red2
   out rgb
   name Shuffle1
   xpos 0
   ypos -347
  }
set Nfdd83400 [stack 0]
  Dot {
   name Dot1
   xpos 315
   ypos 289
  }
push $Nfdd83400
  Unpremult {
   name Unpremult1
   xpos 0
   ypos -286
   disable {{!parent.unpre}}
  }
  NoOp {
   name Plane
   xpos 0
   ypos -218
   addUserKnob {20 User}
   addUserKnob {18 pick l "User Picked Plane" R -1 1}
   pick {0 0 1}
   addUserKnob {6 pick_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
   addUserKnob {20 calc l "Internal Conversions"}
   addUserKnob {18 picked}
   picked {0 {"(atan2(pick.r, pick.b))"} 0}
   addUserKnob {6 picked_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis10.world_matrix.0} {parent.Axis10.world_matrix.1} {parent.Axis10.world_matrix.2}}
        {{parent.Axis10.world_matrix.4} {parent.Axis10.world_matrix.5} {parent.Axis10.world_matrix.6}}
        {{parent.Axis10.world_matrix.8} {parent.Axis10.world_matrix.9} {parent.Axis10.world_matrix.10}}
   }
   name ColorMatrix2
   xpos 0
   ypos -148
   disable {{parent.yoffset==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis2.world_matrix.0} {parent.Axis2.world_matrix.1} {parent.Axis2.world_matrix.2}}
        {{parent.Axis2.world_matrix.4} {parent.Axis2.world_matrix.5} {parent.Axis2.world_matrix.6}}
        {{parent.Axis2.world_matrix.8} {parent.Axis2.world_matrix.9} {parent.Axis2.world_matrix.10}}
   }
   name ColorMatrix3
   xpos 0
   ypos -42
   disable {{parent.xzrot==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis5.world_matrix.0} {parent.Axis5.world_matrix.1} {parent.Axis5.world_matrix.2}}
        {{parent.Axis5.world_matrix.4} {parent.Axis5.world_matrix.5} {parent.Axis5.world_matrix.6}}
        {{parent.Axis5.world_matrix.8} {parent.Axis5.world_matrix.9} {parent.Axis5.world_matrix.10}}
   }
   name ColorMatrix5
   xpos 0
   ypos 54
   disable {{parent.xzrot==0}}
  }
  Expression {
   temp_name0 nx
   temp_expr0 parent.Plane.pick.r
   temp_name1 ny
   temp_expr1 parent.Plane.pick.g
   temp_name2 nz
   temp_expr2 parent.Plane.pick.b
   channel0 {rgba.red -rgba.green -rgba.blue -rgba.alpha}
   expr0 r*nx
   channel1 {-rgba.red rgba.green -rgba.blue none}
   expr1 g*ny
   channel2 {-rgba.red -rgba.green rgba.blue none}
   expr2 b*nz
   channel3 {none none none -rgba.alpha}
   name Expression1
   xpos 0
   ypos 121
   cached true
  }
  Expression {
   expr3 clamp(r+g+b)
   name Expression3
   xpos 0
   ypos 187
  }
  Invert {
   channels alpha
   name Invert1
   xpos 0
   ypos 249
   disable {{!parent.inv}}
  }
  Expression {
   expr3 pow(a,max(1,parent.exp))
   name Expression4
   xpos 0
   ypos 317
  }
  Grade {
   channels alpha
   blackpoint {{-parent.mblack}}
   white {{parent.mgain}}
   gamma {{max(0.001,parent.mgamma)}}
   white_clamp true
   name Grade1
   xpos 0
   ypos 369
  }
  ChannelMerge {
   inputs 2
   operation multiply
   name ChannelMerge1
   xpos 0
   ypos 444
   disable {{!parent.amask}}
  }
push 0
  Merge2 {
   inputs 2+1
   operation copy
   also_merge all
   name Merge1
   label "[ expr { [value mix] == 1 ? \" \" : [concat Mix: [value mix]] } ]"
   xpos 0
   ypos 544
  }
  Output {
   name Output1
   xpos 0
   ypos 623
  }
 end_group
push $Nff59a400
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.blue 0 2 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.red 0 0"
  name Shuffle33
  xpos 6194
  ypos 973
 }
 Grade {
  channels rgba
  white 0.18
  name Grade20
  xpos 6194
  ypos 1004
 }
 Grade {
  inputs 1+1
  white 4
  name Grade21
  xpos 6194
  ypos 1037
 }
add_layer {facingratio facingratio.red facingratio.green facingratio.blue}
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 projectionPrev
  out1 projectionPrev
  fromInput2 {
   {0}
   B
   A
  }
  in2 rgb
  out2 facingratio
  mappings "6 projectionPrev.red 0 0 projectionPrev.red 0 0 projectionPrev.green 0 1 projectionPrev.green 0 1 projectionPrev.blue 0 2 projectionPrev.blue 0 2 rgba.red 1 0 facingratio.red 1 0 rgba.green 1 1 facingratio.green 1 1 rgba.blue 1 2 facingratio.blue 1 2"
  name Shuffle34
  xpos 6194
  ypos 1152
 }
 Dot {
  name Dot86
  xpos 6228
  ypos 1271
 }
add_layer {coverage coverage.red coverage.green coverage.blue}
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 rgb
  out1 coverage
  fromInput2 {
   {0}
   B
   A
  }
  mappings "3 rgba.red 0 0 coverage.red 0 0 rgba.green 0 1 coverage.green 0 1 rgba.blue 0 2 coverage.blue 0 2"
  name Shuffle35
  xpos 6427
  ypos 1268
 }
push $N668ca00
push 0
 Camera3 {
  inputs 2
  translate {{CAM_270_TRANS}}
  focal 100
  name Cam270
  xpos 5833
  ypos 81
 }
 Dot {
  name Dot62
  xpos 5857
  ypos 194
 }
 Dot {
  name Dot63
  xpos 5234
  ypos 194
 }
 Dot {
  name Dot64
  xpos 5234
  ypos 307
 }
 Dot {
  name Dot65
  xpos 4864
  ypos 307
 }
 Dot {
  name Dot66
  xpos 4864
  ypos 735
 }
set N35431800 [stack 0]
 Dot {
  name Dot67
  xpos 4864
  ypos 800
 }
set N35431c00 [stack 0]
 Dot {
  name Dot68
  xpos 4864
  ypos 864
 }
push $N668ca00
push 0
 Camera3 {
  inputs 2
  translate {{CAM_225_TRANS}}
  focal 100
  name Cam225
  xpos 4917
  ypos 74
 }
 Dot {
  name Dot50
  xpos 4941
  ypos 195
 }
set N7969800 [stack 0]
 Dot {
  name Dot69
  xpos 4941
  ypos 478
 }
set N3cb6a400 [stack 0]
 Dot {
  name Dot70
  xpos 4941
  ypos 513
 }
 Constant {
  inputs 0
  channels rgb
  color 1
  name Constant6
  xpos 5621
  ypos 422
 }
 Project3D2 {
  inputs 2
  project_on front
  crop false
  name Project3D11
  xpos 5621
  ypos 510
 }
clone $Cb894de00 {
  xpos 5621
  ypos 579
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel {P.red P.green P.blue}
  N_channel N
  name ScanlineRender16
  xpos 5621
  ypos 861
 }
 Invert {
  name Invert6
  xpos 5621
  ypos 992
 }
push $N35431c00
clone $Cb894de00 {
  inputs 0
  xpos 5278
  ypos 581
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel {P.red P.green P.blue}
  N_channel N
  name ScanlineRender17
  xpos 5278
  ypos 797
 }
 Dot {
  name Dot71
  xpos 5312
  ypos 935
 }
set N3cb6b400 [stack 0]
 FilterErode {
  channels all
  name FilterErode6
  xpos 5511
  ypos 926
 }
 Merge2 {
  inputs 2
  operation multiply
  name Multiply6
  xpos 5511
  ypos 998
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.red 0 0 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.blue 0 2"
  name Shuffle26
  xpos 5511
  ypos 1074
 }
 Grade {
  white 200
  name Grade16
  xpos 5511
  ypos 1172
 }
push $N35431800
push $N3cb6a400
push $N1a1ae400
 Project3D2 {
  inputs 2
  project_on front
  name Project3D12
  xpos 5082
  ypos 475
 }
clone $Cb894de00 {
  xpos 5082
  ypos 582
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender18
  xpos 5082
  ypos 732
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  out1 projectionPrev
  fromInput2 {
   {0}
   B
  }
  mappings "3 rgba.red 0 0 projectionPrev.red 0 0 rgba.green 0 1 projectionPrev.green 0 1 rgba.blue 0 2 projectionPrev.blue 0 2"
  name Shuffle27
  xpos 5082
  ypos 1156
 }
push $N3cb6b400
 Dot {
  name Dot72
  xpos 5202
  ypos 935
 }
 Group {
  name NormalsRotate6
  onCreate "\nn=nuke.thisNode()\nn['mblack'].setFlag(0x0000000000000004)\nn['mgain'].setFlag(0x0000000000000004)\nn['mgamma'].setFlag(0x0000000000000004)\n"
  tile_color 0xff00ff
  xpos 5168
  ypos 1041
  addUserKnob {20 User}
  addUserKnob {41 in l "Normals in" t "Select the layer containing the \nnormals" T Shuffle1.in}
  addUserKnob {41 pick l "Pick Plane" T Plane.pick}
  addUserKnob {22 planereset l Reset -STARTLINE T "nuke.thisNode().knob(\"pick\").setValue(0,0)\nnuke.thisNode().knob(\"pick\").setValue(0,1)\nnuke.thisNode().knob(\"pick\").setValue(1,2)"}
  addUserKnob {26 ""}
  addUserKnob {26 divider_2 l "" +STARTLINE T " "}
  addUserKnob {26 manual l "<b>Manual Rotation</b>" -STARTLINE T "  "}
  addUserKnob {22 rotreset l Reset -STARTLINE T "nuke.thisNode().knob(\"yoffset\").setValue(0)\nnuke.thisNode().knob(\"xzrot\").setValue(0)"}
  addUserKnob {7 yoffset l Horizontal t "Rotate around the world Y axis" R -180 180}
  yoffset {{"degrees(atan2(Cam270.world_matrix.2, Cam270.world_matrix.10))"}}
  addUserKnob {7 xzrot l Vertical t "Rotates around the rotated X axis" R -180 180}
  addUserKnob {26 ""}
  addUserKnob {26 matte l "@b;Matte Output" T "      "}
  addUserKnob {6 inv l "Invert    " t "This happens before the matte \ntweaks" -STARTLINE}
  addUserKnob {6 amask l "Mask by Alpha    " -STARTLINE}
  addUserKnob {6 unpre l Unpremult -STARTLINE}
  addUserKnob {7 exp l Exponent t "Exponential falloff" R 1 10}
  exp 2
  addUserKnob {22 expreset l Reset -STARTLINE T "nuke.thisNode().knob(\"exp\").setValue(2)"}
  addUserKnob {7 mblack l Black R -1 1}
  addUserKnob {22 mblackreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mblack\").setValue(0)"}
  addUserKnob {7 mgain l White R 0 4}
  mgain 1
  addUserKnob {22 mgainreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgain\").setValue(1)"}
  addUserKnob {7 mgamma l Gamma R 0 4}
  mgamma 1
  addUserKnob {22 mgammareset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgamma\").setValue(1)"}
  addUserKnob {26 ""}
  addUserKnob {26 "" l mask T ""}
  addUserKnob {41 maskChannelInput l "" -STARTLINE T Merge1.maskChannelInput}
  addUserKnob {41 inject -STARTLINE T Merge1.inject}
  addUserKnob {41 invert_mask l invert -STARTLINE T Merge1.invert_mask}
  addUserKnob {41 fringe -STARTLINE T Merge1.fringe}
  addUserKnob {41 mix T Merge1.mix}
  addUserKnob {20 info l Info}
  addUserKnob {26 infotext l "" +STARTLINE T "W_SuperNormal generates a surface angle based matte using normals.\n\n1. Select the layer containing normals in the dropdown menu.\n2. Enable color picker and pick the point where you want the matte to be white.\n  (I look at the alpha output, hold ctrl+alt and \"glide\" over the surfaces.)\n3. You can also manually rotate the matte. When you colorpick a new point,\n  it is recommended that you reset the manual rotation values to 0.\n"}
  addUserKnob {20 v2_1_group l "v2.1 - Feb 2019" n 1}
  v2_1_group 0
  addUserKnob {26 v2_1_text l "" +STARTLINE T "  -Manual rotation working as originally envisioned: It is more intuitive \n   and faster to reach any desired angle with horizontal(Y) and vertical\n   rotation than with separate XYZ rotations.\n  -General cleanup & refinements.\n"}
  addUserKnob {20 endGroup n -1}
  addUserKnob {20 v2group l "v2.0 - 2018" n 1}
  v2group 0
  addUserKnob {26 v2text l "" +STARTLINE T "  -Adopted a different method for rotating normals shown to me by Daniel Pelc\n  -Simpler math for converting normals into a matte with the help of Erwan Leroy\n"}
  addUserKnob {20 endGroup_1 l endGroup n -1}
  addUserKnob {26 v1_1_text l "" +STARTLINE T "    v1.1 - 2016"}
  addUserKnob {26 ""}
  addUserKnob {26 spacer_1 l "" +STARTLINE T "     "}
  addUserKnob {26 copyright l "&#169;  Wes Heo" -STARTLINE T " "}
 }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.yoffset} 0}
   name Axis10
   label H
   xpos -173
   ypos -163
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {{parent.xzrot} {-degrees(parent.Plane.picked.g)} 0}
   name Axis2
   label V
   xpos -171
   ypos -62
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.Axis2.rotate.y} 0}
   name Axis5
   label V
   xpos -170
   ypos 34
  }
  Input {
   inputs 0
   name Inputmask
   xpos 132
   ypos 544
   number 1
  }
  Input {
   inputs 0
   name N
   xpos 0
   ypos -425
  }
  Shuffle {
   in N
   alpha red2
   out rgb
   name Shuffle1
   xpos 0
   ypos -347
  }
set N31c1ed00 [stack 0]
  Dot {
   name Dot1
   xpos 315
   ypos 289
  }
push $N31c1ed00
  Unpremult {
   name Unpremult1
   xpos 0
   ypos -286
   disable {{!parent.unpre}}
  }
  NoOp {
   name Plane
   xpos 0
   ypos -218
   addUserKnob {20 User}
   addUserKnob {18 pick l "User Picked Plane" R -1 1}
   pick {0 0 1}
   addUserKnob {6 pick_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
   addUserKnob {20 calc l "Internal Conversions"}
   addUserKnob {18 picked}
   picked {0 {"(atan2(pick.r, pick.b))"} 0}
   addUserKnob {6 picked_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis10.world_matrix.0} {parent.Axis10.world_matrix.1} {parent.Axis10.world_matrix.2}}
        {{parent.Axis10.world_matrix.4} {parent.Axis10.world_matrix.5} {parent.Axis10.world_matrix.6}}
        {{parent.Axis10.world_matrix.8} {parent.Axis10.world_matrix.9} {parent.Axis10.world_matrix.10}}
   }
   name ColorMatrix2
   xpos 0
   ypos -148
   disable {{parent.yoffset==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis2.world_matrix.0} {parent.Axis2.world_matrix.1} {parent.Axis2.world_matrix.2}}
        {{parent.Axis2.world_matrix.4} {parent.Axis2.world_matrix.5} {parent.Axis2.world_matrix.6}}
        {{parent.Axis2.world_matrix.8} {parent.Axis2.world_matrix.9} {parent.Axis2.world_matrix.10}}
   }
   name ColorMatrix3
   xpos 0
   ypos -42
   disable {{parent.xzrot==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis5.world_matrix.0} {parent.Axis5.world_matrix.1} {parent.Axis5.world_matrix.2}}
        {{parent.Axis5.world_matrix.4} {parent.Axis5.world_matrix.5} {parent.Axis5.world_matrix.6}}
        {{parent.Axis5.world_matrix.8} {parent.Axis5.world_matrix.9} {parent.Axis5.world_matrix.10}}
   }
   name ColorMatrix5
   xpos 0
   ypos 54
   disable {{parent.xzrot==0}}
  }
  Expression {
   temp_name0 nx
   temp_expr0 parent.Plane.pick.r
   temp_name1 ny
   temp_expr1 parent.Plane.pick.g
   temp_name2 nz
   temp_expr2 parent.Plane.pick.b
   channel0 {rgba.red -rgba.green -rgba.blue -rgba.alpha}
   expr0 r*nx
   channel1 {-rgba.red rgba.green -rgba.blue none}
   expr1 g*ny
   channel2 {-rgba.red -rgba.green rgba.blue none}
   expr2 b*nz
   channel3 {none none none -rgba.alpha}
   name Expression1
   xpos 0
   ypos 121
   cached true
  }
  Expression {
   expr3 clamp(r+g+b)
   name Expression3
   xpos 0
   ypos 187
  }
  Invert {
   channels alpha
   name Invert1
   xpos 0
   ypos 249
   disable {{!parent.inv}}
  }
  Expression {
   expr3 pow(a,max(1,parent.exp))
   name Expression4
   xpos 0
   ypos 317
  }
  Grade {
   channels alpha
   blackpoint {{-parent.mblack}}
   white {{parent.mgain}}
   gamma {{max(0.001,parent.mgamma)}}
   white_clamp true
   name Grade1
   xpos 0
   ypos 369
  }
  ChannelMerge {
   inputs 2
   operation multiply
   name ChannelMerge1
   xpos 0
   ypos 444
   disable {{!parent.amask}}
  }
push 0
  Merge2 {
   inputs 2+1
   operation copy
   also_merge all
   name Merge1
   label "[ expr { [value mix] == 1 ? \" \" : [concat Mix: [value mix]] } ]"
   xpos 0
   ypos 544
  }
  Output {
   name Output1
   xpos 0
   ypos 623
  }
 end_group
push $N3cb6b400
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.blue 0 2 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.red 0 0"
  name Shuffle28
  xpos 5278
  ypos 977
 }
 Grade {
  channels rgba
  white 0.18
  name Grade17
  xpos 5278
  ypos 1008
 }
 Grade {
  inputs 1+1
  white 4
  name Grade18
  xpos 5278
  ypos 1041
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 projectionPrev
  out1 projectionPrev
  fromInput2 {
   {0}
   B
   A
  }
  in2 rgb
  out2 facingratio
  mappings "6 projectionPrev.red 0 0 projectionPrev.red 0 0 projectionPrev.green 0 1 projectionPrev.green 0 1 projectionPrev.blue 0 2 projectionPrev.blue 0 2 rgba.red 1 0 facingratio.red 1 0 rgba.green 1 1 facingratio.green 1 1 rgba.blue 1 2 facingratio.blue 1 2"
  name Shuffle29
  xpos 5278
  ypos 1156
 }
 Dot {
  name Dot73
  xpos 5312
  ypos 1275
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 rgb
  out1 coverage
  fromInput2 {
   {0}
   B
   A
  }
  mappings "3 rgba.red 0 0 coverage.red 0 0 rgba.green 0 1 coverage.green 0 1 rgba.blue 0 2 coverage.blue 0 2"
  name Shuffle30
  xpos 5511
  ypos 1272
 }
push $N7969800
 Dot {
  name Dot51
  xpos 4318
  ypos 195
 }
 Dot {
  name Dot52
  xpos 4318
  ypos 305
 }
 Dot {
  name Dot53
  xpos 3948
  ypos 305
 }
 Dot {
  name Dot54
  xpos 3948
  ypos 733
 }
set N17e84800 [stack 0]
 Dot {
  name Dot55
  xpos 3948
  ypos 798
 }
set N17e84c00 [stack 0]
 Dot {
  name Dot56
  xpos 3948
  ypos 862
 }
push $N668ca00
push 0
 Camera3 {
  inputs 2
  translate {{CAM_180_TRANS}}
  focal 100
  name Cam180
  xpos 4001
  ypos 107
 }
 Dot {
  name Dot38
  xpos 4025
  ypos 212
 }
set Nfd7bd400 [stack 0]
 Dot {
  name Dot57
  xpos 4025
  ypos 476
 }
set N17e85400 [stack 0]
 Dot {
  name Dot58
  xpos 4025
  ypos 511
 }
 Constant {
  inputs 0
  channels rgb
  color 1
  name Constant5
  xpos 4705
  ypos 424
 }
 Project3D2 {
  inputs 2
  project_on front
  crop false
  name Project3D9
  xpos 4705
  ypos 508
 }
clone $Cb894de00 {
  xpos 4705
  ypos 577
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender13
  xpos 4705
  ypos 859
 }
 Invert {
  name Invert5
  xpos 4705
  ypos 990
 }
push $N17e84c00
clone $Cb894de00 {
  inputs 0
  xpos 4362
  ypos 579
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender14
  xpos 4362
  ypos 795
 }
 Dot {
  name Dot59
  xpos 4396
  ypos 933
 }
set N4388800 [stack 0]
 FilterErode {
  channels all
  name FilterErode5
  xpos 4595
  ypos 924
 }
 Merge2 {
  inputs 2
  operation multiply
  name Multiply5
  xpos 4595
  ypos 996
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.red 0 0 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.blue 0 2"
  name Shuffle21
  xpos 4595
  ypos 1072
 }
 Grade {
  white 200
  name Grade13
  xpos 4595
  ypos 1170
 }
push $N17e84800
push $N17e85400
push $N1a1ae000
 Project3D2 {
  inputs 2
  project_on front
  name Project3D10
  xpos 4166
  ypos 473
 }
clone $Cb894de00 {
  xpos 4166
  ypos 580
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel {P.red P.green P.blue}
  N_channel N
  name ScanlineRender15
  xpos 4166
  ypos 730
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  out1 projectionPrev
  fromInput2 {
   {0}
   B
  }
  mappings "3 rgba.red 0 0 projectionPrev.red 0 0 rgba.green 0 1 projectionPrev.green 0 1 rgba.blue 0 2 projectionPrev.blue 0 2"
  name Shuffle22
  xpos 4166
  ypos 1154
 }
push $N4388800
 Dot {
  name Dot60
  xpos 4286
  ypos 933
 }
 Group {
  name NormalsRotate5
  onCreate "\nn=nuke.thisNode()\nn['mblack'].setFlag(0x0000000000000004)\nn['mgain'].setFlag(0x0000000000000004)\nn['mgamma'].setFlag(0x0000000000000004)\n"
  tile_color 0xff00ff
  xpos 4252
  ypos 1039
  addUserKnob {20 User}
  addUserKnob {41 in l "Normals in" t "Select the layer containing the \nnormals" T Shuffle1.in}
  addUserKnob {41 pick l "Pick Plane" T Plane.pick}
  addUserKnob {22 planereset l Reset -STARTLINE T "nuke.thisNode().knob(\"pick\").setValue(0,0)\nnuke.thisNode().knob(\"pick\").setValue(0,1)\nnuke.thisNode().knob(\"pick\").setValue(1,2)"}
  addUserKnob {26 ""}
  addUserKnob {26 divider_2 l "" +STARTLINE T " "}
  addUserKnob {26 manual l "<b>Manual Rotation</b>" -STARTLINE T "  "}
  addUserKnob {22 rotreset l Reset -STARTLINE T "nuke.thisNode().knob(\"yoffset\").setValue(0)\nnuke.thisNode().knob(\"xzrot\").setValue(0)"}
  addUserKnob {7 yoffset l Horizontal t "Rotate around the world Y axis" R -180 180}
  yoffset {{"degrees(atan2(Cam225.world_matrix.2, Cam225.world_matrix.10))"}}
  addUserKnob {7 xzrot l Vertical t "Rotates around the rotated X axis" R -180 180}
  addUserKnob {26 ""}
  addUserKnob {26 matte l "@b;Matte Output" T "      "}
  addUserKnob {6 inv l "Invert    " t "This happens before the matte \ntweaks" -STARTLINE}
  addUserKnob {6 amask l "Mask by Alpha    " -STARTLINE}
  addUserKnob {6 unpre l Unpremult -STARTLINE}
  addUserKnob {7 exp l Exponent t "Exponential falloff" R 1 10}
  exp 2
  addUserKnob {22 expreset l Reset -STARTLINE T "nuke.thisNode().knob(\"exp\").setValue(2)"}
  addUserKnob {7 mblack l Black R -1 1}
  addUserKnob {22 mblackreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mblack\").setValue(0)"}
  addUserKnob {7 mgain l White R 0 4}
  mgain 1
  addUserKnob {22 mgainreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgain\").setValue(1)"}
  addUserKnob {7 mgamma l Gamma R 0 4}
  mgamma 1
  addUserKnob {22 mgammareset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgamma\").setValue(1)"}
  addUserKnob {26 ""}
  addUserKnob {26 "" l mask T ""}
  addUserKnob {41 maskChannelInput l "" -STARTLINE T Merge1.maskChannelInput}
  addUserKnob {41 inject -STARTLINE T Merge1.inject}
  addUserKnob {41 invert_mask l invert -STARTLINE T Merge1.invert_mask}
  addUserKnob {41 fringe -STARTLINE T Merge1.fringe}
  addUserKnob {41 mix T Merge1.mix}
  addUserKnob {20 info l Info}
  addUserKnob {26 infotext l "" +STARTLINE T "W_SuperNormal generates a surface angle based matte using normals.\n\n1. Select the layer containing normals in the dropdown menu.\n2. Enable color picker and pick the point where you want the matte to be white.\n  (I look at the alpha output, hold ctrl+alt and \"glide\" over the surfaces.)\n3. You can also manually rotate the matte. When you colorpick a new point,\n  it is recommended that you reset the manual rotation values to 0.\n"}
  addUserKnob {20 v2_1_group l "v2.1 - Feb 2019" n 1}
  v2_1_group 0
  addUserKnob {26 v2_1_text l "" +STARTLINE T "  -Manual rotation working as originally envisioned: It is more intuitive \n   and faster to reach any desired angle with horizontal(Y) and vertical\n   rotation than with separate XYZ rotations.\n  -General cleanup & refinements.\n"}
  addUserKnob {20 endGroup n -1}
  addUserKnob {20 v2group l "v2.0 - 2018" n 1}
  v2group 0
  addUserKnob {26 v2text l "" +STARTLINE T "  -Adopted a different method for rotating normals shown to me by Daniel Pelc\n  -Simpler math for converting normals into a matte with the help of Erwan Leroy\n"}
  addUserKnob {20 endGroup_1 l endGroup n -1}
  addUserKnob {26 v1_1_text l "" +STARTLINE T "    v1.1 - 2016"}
  addUserKnob {26 ""}
  addUserKnob {26 spacer_1 l "" +STARTLINE T "     "}
  addUserKnob {26 copyright l "&#169;  Wes Heo" -STARTLINE T " "}
 }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.yoffset} 0}
   name Axis10
   label H
   xpos -173
   ypos -163
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {{parent.xzrot} {-degrees(parent.Plane.picked.g)} 0}
   name Axis2
   label V
   xpos -171
   ypos -62
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.Axis2.rotate.y} 0}
   name Axis5
   label V
   xpos -170
   ypos 34
  }
  Input {
   inputs 0
   name Inputmask
   xpos 132
   ypos 544
   number 1
  }
  Input {
   inputs 0
   name N
   xpos 0
   ypos -425
  }
  Shuffle {
   in N
   alpha red2
   out rgb
   name Shuffle1
   xpos 0
   ypos -347
  }
set N2f548000 [stack 0]
  Dot {
   name Dot1
   xpos 315
   ypos 289
  }
push $N2f548000
  Unpremult {
   name Unpremult1
   xpos 0
   ypos -286
   disable {{!parent.unpre}}
  }
  NoOp {
   name Plane
   xpos 0
   ypos -218
   addUserKnob {20 User}
   addUserKnob {18 pick l "User Picked Plane" R -1 1}
   pick {0 0 1}
   addUserKnob {6 pick_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
   addUserKnob {20 calc l "Internal Conversions"}
   addUserKnob {18 picked}
   picked {0 {"(atan2(pick.r, pick.b))"} 0}
   addUserKnob {6 picked_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis10.world_matrix.0} {parent.Axis10.world_matrix.1} {parent.Axis10.world_matrix.2}}
        {{parent.Axis10.world_matrix.4} {parent.Axis10.world_matrix.5} {parent.Axis10.world_matrix.6}}
        {{parent.Axis10.world_matrix.8} {parent.Axis10.world_matrix.9} {parent.Axis10.world_matrix.10}}
   }
   name ColorMatrix2
   xpos 0
   ypos -148
   disable {{parent.yoffset==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis2.world_matrix.0} {parent.Axis2.world_matrix.1} {parent.Axis2.world_matrix.2}}
        {{parent.Axis2.world_matrix.4} {parent.Axis2.world_matrix.5} {parent.Axis2.world_matrix.6}}
        {{parent.Axis2.world_matrix.8} {parent.Axis2.world_matrix.9} {parent.Axis2.world_matrix.10}}
   }
   name ColorMatrix3
   xpos 0
   ypos -42
   disable {{parent.xzrot==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis5.world_matrix.0} {parent.Axis5.world_matrix.1} {parent.Axis5.world_matrix.2}}
        {{parent.Axis5.world_matrix.4} {parent.Axis5.world_matrix.5} {parent.Axis5.world_matrix.6}}
        {{parent.Axis5.world_matrix.8} {parent.Axis5.world_matrix.9} {parent.Axis5.world_matrix.10}}
   }
   name ColorMatrix5
   xpos 0
   ypos 54
   disable {{parent.xzrot==0}}
  }
  Expression {
   temp_name0 nx
   temp_expr0 parent.Plane.pick.r
   temp_name1 ny
   temp_expr1 parent.Plane.pick.g
   temp_name2 nz
   temp_expr2 parent.Plane.pick.b
   channel0 {rgba.red -rgba.green -rgba.blue -rgba.alpha}
   expr0 r*nx
   channel1 {-rgba.red rgba.green -rgba.blue none}
   expr1 g*ny
   channel2 {-rgba.red -rgba.green rgba.blue none}
   expr2 b*nz
   channel3 {none none none -rgba.alpha}
   name Expression1
   xpos 0
   ypos 121
   cached true
  }
  Expression {
   expr3 clamp(r+g+b)
   name Expression3
   xpos 0
   ypos 187
  }
  Invert {
   channels alpha
   name Invert1
   xpos 0
   ypos 249
   disable {{!parent.inv}}
  }
  Expression {
   expr3 pow(a,max(1,parent.exp))
   name Expression4
   xpos 0
   ypos 317
  }
  Grade {
   channels alpha
   blackpoint {{-parent.mblack}}
   white {{parent.mgain}}
   gamma {{max(0.001,parent.mgamma)}}
   white_clamp true
   name Grade1
   xpos 0
   ypos 369
  }
  ChannelMerge {
   inputs 2
   operation multiply
   name ChannelMerge1
   xpos 0
   ypos 444
   disable {{!parent.amask}}
  }
push 0
  Merge2 {
   inputs 2+1
   operation copy
   also_merge all
   name Merge1
   label "[ expr { [value mix] == 1 ? \" \" : [concat Mix: [value mix]] } ]"
   xpos 0
   ypos 544
  }
  Output {
   name Output1
   xpos 0
   ypos 623
  }
 end_group
push $N4388800
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.blue 0 2 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.red 0 0"
  name Shuffle23
  xpos 4362
  ypos 975
 }
 Grade {
  channels rgba
  white 0.18
  name Grade14
  xpos 4362
  ypos 1006
 }
 Grade {
  inputs 1+1
  white 4
  name Grade15
  xpos 4362
  ypos 1039
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 projectionPrev
  out1 projectionPrev
  fromInput2 {
   {0}
   B
   A
  }
  in2 rgb
  out2 facingratio
  mappings "6 projectionPrev.red 0 0 projectionPrev.red 0 0 projectionPrev.green 0 1 projectionPrev.green 0 1 projectionPrev.blue 0 2 projectionPrev.blue 0 2 rgba.red 1 0 facingratio.red 1 0 rgba.green 1 1 facingratio.green 1 1 rgba.blue 1 2 facingratio.blue 1 2"
  name Shuffle24
  xpos 4362
  ypos 1154
 }
 Dot {
  name Dot61
  xpos 4396
  ypos 1273
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 rgb
  out1 coverage
  fromInput2 {
   {0}
   B
   A
  }
  mappings "3 rgba.red 0 0 coverage.red 0 0 rgba.green 0 1 coverage.green 0 1 rgba.blue 0 2 coverage.blue 0 2"
  name Shuffle25
  xpos 4595
  ypos 1270
 }
push $Nfd7bd400
 Dot {
  name Dot39
  xpos 3402
  ypos 212
 }
 Dot {
  name Dot40
  xpos 3402
  ypos 325
 }
 Dot {
  name Dot41
  xpos 3032
  ypos 325
 }
 Dot {
  name Dot42
  xpos 3032
  ypos 753
 }
set N1248400 [stack 0]
 Dot {
  name Dot43
  xpos 3032
  ypos 818
 }
set N1248800 [stack 0]
 Dot {
  name Dot44
  xpos 3032
  ypos 882
 }
push $N668ca00
push 0
 Camera3 {
  inputs 2
  translate {{CAM_135_TRANS}}
  focal 100
  name Cam135
  xpos 3085
  ypos 116
 }
 Dot {
  name Dot26
  xpos 3109
  ypos 213
 }
set N32090800 [stack 0]
 Dot {
  name Dot45
  xpos 3109
  ypos 496
 }
set N1249000 [stack 0]
 Dot {
  name Dot46
  xpos 3109
  ypos 531
 }
 Constant {
  inputs 0
  channels rgb
  color 1
  name Constant4
  xpos 3789
  ypos 434
 }
 Project3D2 {
  inputs 2
  project_on front
  crop false
  name Project3D6
  xpos 3789
  ypos 528
 }
clone $Cb894de00 {
  xpos 3789
  ypos 597
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel {P.red P.green P.blue}
  N_channel N
  name ScanlineRender10
  xpos 3789
  ypos 879
 }
 Invert {
  name Invert4
  xpos 3789
  ypos 1010
 }
push $N1248800
clone $Cb894de00 {
  inputs 0
  xpos 3446
  ypos 599
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel {P.red P.green P.blue}
  N_channel N
  name ScanlineRender11
  xpos 3446
  ypos 815
 }
 Dot {
  name Dot47
  xpos 3480
  ypos 953
 }
set Nddc82000 [stack 0]
 FilterErode {
  channels all
  name FilterErode4
  xpos 3679
  ypos 944
 }
 Merge2 {
  inputs 2
  operation multiply
  name Multiply3
  xpos 3679
  ypos 1016
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.red 0 0 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.blue 0 2"
  name Shuffle16
  xpos 3679
  ypos 1092
 }
 Grade {
  white 200
  name Grade10
  xpos 3679
  ypos 1190
 }
push $N1248400
push $N1249000
push $N19093c00
 Project3D2 {
  inputs 2
  project_on front
  name Project3D7
  xpos 3250
  ypos 493
 }
clone $Cb894de00 {
  xpos 3250
  ypos 600
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender12
  xpos 3250
  ypos 750
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  out1 projectionPrev
  fromInput2 {
   {0}
   B
  }
  mappings "3 rgba.red 0 0 projectionPrev.red 0 0 rgba.green 0 1 projectionPrev.green 0 1 rgba.blue 0 2 projectionPrev.blue 0 2"
  name Shuffle17
  xpos 3250
  ypos 1174
 }
push $Nddc82000
 Dot {
  name Dot48
  xpos 3370
  ypos 953
 }
 Group {
  name NormalsRotate4
  onCreate "\nn=nuke.thisNode()\nn['mblack'].setFlag(0x0000000000000004)\nn['mgain'].setFlag(0x0000000000000004)\nn['mgamma'].setFlag(0x0000000000000004)\n"
  tile_color 0xff00ff
  xpos 3336
  ypos 1059
  addUserKnob {20 User}
  addUserKnob {41 in l "Normals in" t "Select the layer containing the \nnormals" T Shuffle1.in}
  addUserKnob {41 pick l "Pick Plane" T Plane.pick}
  addUserKnob {22 planereset l Reset -STARTLINE T "nuke.thisNode().knob(\"pick\").setValue(0,0)\nnuke.thisNode().knob(\"pick\").setValue(0,1)\nnuke.thisNode().knob(\"pick\").setValue(1,2)"}
  addUserKnob {26 ""}
  addUserKnob {26 divider_2 l "" +STARTLINE T " "}
  addUserKnob {26 manual l "<b>Manual Rotation</b>" -STARTLINE T "  "}
  addUserKnob {22 rotreset l Reset -STARTLINE T "nuke.thisNode().knob(\"yoffset\").setValue(0)\nnuke.thisNode().knob(\"xzrot\").setValue(0)"}
  addUserKnob {7 yoffset l Horizontal t "Rotate around the world Y axis" R -180 180}
  yoffset {{"degrees(atan2(Cam180.world_matrix.2, Cam180.world_matrix.10))"}}
  addUserKnob {7 xzrot l Vertical t "Rotates around the rotated X axis" R -180 180}
  addUserKnob {26 ""}
  addUserKnob {26 matte l "@b;Matte Output" T "      "}
  addUserKnob {6 inv l "Invert    " t "This happens before the matte \ntweaks" -STARTLINE}
  addUserKnob {6 amask l "Mask by Alpha    " -STARTLINE}
  addUserKnob {6 unpre l Unpremult -STARTLINE}
  addUserKnob {7 exp l Exponent t "Exponential falloff" R 1 10}
  exp 2
  addUserKnob {22 expreset l Reset -STARTLINE T "nuke.thisNode().knob(\"exp\").setValue(2)"}
  addUserKnob {7 mblack l Black R -1 1}
  addUserKnob {22 mblackreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mblack\").setValue(0)"}
  addUserKnob {7 mgain l White R 0 4}
  mgain 1
  addUserKnob {22 mgainreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgain\").setValue(1)"}
  addUserKnob {7 mgamma l Gamma R 0 4}
  mgamma 1
  addUserKnob {22 mgammareset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgamma\").setValue(1)"}
  addUserKnob {26 ""}
  addUserKnob {26 "" l mask T ""}
  addUserKnob {41 maskChannelInput l "" -STARTLINE T Merge1.maskChannelInput}
  addUserKnob {41 inject -STARTLINE T Merge1.inject}
  addUserKnob {41 invert_mask l invert -STARTLINE T Merge1.invert_mask}
  addUserKnob {41 fringe -STARTLINE T Merge1.fringe}
  addUserKnob {41 mix T Merge1.mix}
  addUserKnob {20 info l Info}
  addUserKnob {26 infotext l "" +STARTLINE T "W_SuperNormal generates a surface angle based matte using normals.\n\n1. Select the layer containing normals in the dropdown menu.\n2. Enable color picker and pick the point where you want the matte to be white.\n  (I look at the alpha output, hold ctrl+alt and \"glide\" over the surfaces.)\n3. You can also manually rotate the matte. When you colorpick a new point,\n  it is recommended that you reset the manual rotation values to 0.\n"}
  addUserKnob {20 v2_1_group l "v2.1 - Feb 2019" n 1}
  v2_1_group 0
  addUserKnob {26 v2_1_text l "" +STARTLINE T "  -Manual rotation working as originally envisioned: It is more intuitive \n   and faster to reach any desired angle with horizontal(Y) and vertical\n   rotation than with separate XYZ rotations.\n  -General cleanup & refinements.\n"}
  addUserKnob {20 endGroup n -1}
  addUserKnob {20 v2group l "v2.0 - 2018" n 1}
  v2group 0
  addUserKnob {26 v2text l "" +STARTLINE T "  -Adopted a different method for rotating normals shown to me by Daniel Pelc\n  -Simpler math for converting normals into a matte with the help of Erwan Leroy\n"}
  addUserKnob {20 endGroup_1 l endGroup n -1}
  addUserKnob {26 v1_1_text l "" +STARTLINE T "    v1.1 - 2016"}
  addUserKnob {26 ""}
  addUserKnob {26 spacer_1 l "" +STARTLINE T "     "}
  addUserKnob {26 copyright l "&#169;  Wes Heo" -STARTLINE T " "}
 }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.yoffset} 0}
   name Axis10
   label H
   xpos -173
   ypos -163
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {{parent.xzrot} {-degrees(parent.Plane.picked.g)} 0}
   name Axis2
   label V
   xpos -171
   ypos -62
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.Axis2.rotate.y} 0}
   name Axis5
   label V
   xpos -170
   ypos 34
  }
  Input {
   inputs 0
   name Inputmask
   xpos 132
   ypos 544
   number 1
  }
  Input {
   inputs 0
   name N
   xpos 0
   ypos -425
  }
  Shuffle {
   in N
   alpha red2
   out rgb
   name Shuffle1
   xpos 0
   ypos -347
  }
set Na03aa00 [stack 0]
  Dot {
   name Dot1
   xpos 315
   ypos 289
  }
push $Na03aa00
  Unpremult {
   name Unpremult1
   xpos 0
   ypos -286
   disable {{!parent.unpre}}
  }
  NoOp {
   name Plane
   xpos 0
   ypos -218
   addUserKnob {20 User}
   addUserKnob {18 pick l "User Picked Plane" R -1 1}
   pick {0 0 1}
   addUserKnob {6 pick_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
   addUserKnob {20 calc l "Internal Conversions"}
   addUserKnob {18 picked}
   picked {0 {"(atan2(pick.r, pick.b))"} 0}
   addUserKnob {6 picked_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis10.world_matrix.0} {parent.Axis10.world_matrix.1} {parent.Axis10.world_matrix.2}}
        {{parent.Axis10.world_matrix.4} {parent.Axis10.world_matrix.5} {parent.Axis10.world_matrix.6}}
        {{parent.Axis10.world_matrix.8} {parent.Axis10.world_matrix.9} {parent.Axis10.world_matrix.10}}
   }
   name ColorMatrix2
   xpos 0
   ypos -148
   disable {{parent.yoffset==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis2.world_matrix.0} {parent.Axis2.world_matrix.1} {parent.Axis2.world_matrix.2}}
        {{parent.Axis2.world_matrix.4} {parent.Axis2.world_matrix.5} {parent.Axis2.world_matrix.6}}
        {{parent.Axis2.world_matrix.8} {parent.Axis2.world_matrix.9} {parent.Axis2.world_matrix.10}}
   }
   name ColorMatrix3
   xpos 0
   ypos -42
   disable {{parent.xzrot==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis5.world_matrix.0} {parent.Axis5.world_matrix.1} {parent.Axis5.world_matrix.2}}
        {{parent.Axis5.world_matrix.4} {parent.Axis5.world_matrix.5} {parent.Axis5.world_matrix.6}}
        {{parent.Axis5.world_matrix.8} {parent.Axis5.world_matrix.9} {parent.Axis5.world_matrix.10}}
   }
   name ColorMatrix5
   xpos 0
   ypos 54
   disable {{parent.xzrot==0}}
  }
  Expression {
   temp_name0 nx
   temp_expr0 parent.Plane.pick.r
   temp_name1 ny
   temp_expr1 parent.Plane.pick.g
   temp_name2 nz
   temp_expr2 parent.Plane.pick.b
   channel0 {rgba.red -rgba.green -rgba.blue -rgba.alpha}
   expr0 r*nx
   channel1 {-rgba.red rgba.green -rgba.blue none}
   expr1 g*ny
   channel2 {-rgba.red -rgba.green rgba.blue none}
   expr2 b*nz
   channel3 {none none none -rgba.alpha}
   name Expression1
   xpos 0
   ypos 121
   cached true
  }
  Expression {
   expr3 clamp(r+g+b)
   name Expression3
   xpos 0
   ypos 187
  }
  Invert {
   channels alpha
   name Invert1
   xpos 0
   ypos 249
   disable {{!parent.inv}}
  }
  Expression {
   expr3 pow(a,max(1,parent.exp))
   name Expression4
   xpos 0
   ypos 317
  }
  Grade {
   channels alpha
   blackpoint {{-parent.mblack}}
   white {{parent.mgain}}
   gamma {{max(0.001,parent.mgamma)}}
   white_clamp true
   name Grade1
   xpos 0
   ypos 369
  }
  ChannelMerge {
   inputs 2
   operation multiply
   name ChannelMerge1
   xpos 0
   ypos 444
   disable {{!parent.amask}}
  }
push 0
  Merge2 {
   inputs 2+1
   operation copy
   also_merge all
   name Merge1
   label "[ expr { [value mix] == 1 ? \" \" : [concat Mix: [value mix]] } ]"
   xpos 0
   ypos 544
  }
  Output {
   name Output1
   xpos 0
   ypos 623
  }
 end_group
push $N4388800
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.blue 0 2 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.red 0 0"
  name Shuffle23
  xpos 4362
  ypos 975
 }
 Grade {
  channels rgba
  white 0.18
  name Grade14
  xpos 4362
  ypos 1006
 }
 Grade {
  inputs 1+1
  white 4
  name Grade15
  xpos 4362
  ypos 1039
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 projectionPrev
  out1 projectionPrev
  fromInput2 {
   {0}
   B
   A
  }
  in2 rgb
  out2 facingratio
  mappings "6 projectionPrev.red 0 0 projectionPrev.red 0 0 projectionPrev.green 0 1 projectionPrev.green 0 1 projectionPrev.blue 0 2 projectionPrev.blue 0 2 rgba.red 1 0 facingratio.red 1 0 rgba.green 1 1 facingratio.green 1 1 rgba.blue 1 2 facingratio.blue 1 2"
  name Shuffle24
  xpos 4362
  ypos 1154
 }
 Dot {
  name Dot61
  xpos 4396
  ypos 1273
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 rgb
  out1 coverage
  fromInput2 {
   {0}
   B
   A
  }
  mappings "3 rgba.red 0 0 coverage.red 0 0 rgba.green 0 1 coverage.green 0 1 rgba.blue 0 2 coverage.blue 0 2"
  name Shuffle25
  xpos 4595
  ypos 1270
 }
push $Nfd7bd400
 Dot {
  name Dot39
  xpos 3402
  ypos 212
 }
 Dot {
  name Dot40
  xpos 3402
  ypos 325
 }
 Dot {
  name Dot41
  xpos 3032
  ypos 325
 }
 Dot {
  name Dot42
  xpos 3032
  ypos 753
 }
set N1248400 [stack 0]
 Dot {
  name Dot43
  xpos 3032
  ypos 818
 }
set N1248800 [stack 0]
 Dot {
  name Dot44
  xpos 3032
  ypos 882
 }
push $N668ca00
push 0
 Camera3 {
  inputs 2
  translate {{CAM_90_TRANS}}
  focal 100
  name Cam90
  xpos 2169
  ypos 110
 }
 Dot {
  name Dot24
  xpos 2193
  ypos 221
 }
set Ndac8fc00 [stack 0]
 Dot {
  name Dot33
  xpos 2193
  ypos 494
 }
set Nff5a6400 [stack 0]
 Dot {
  name Dot34
  xpos 2193
  ypos 529
 }
 Constant {
  inputs 0
  channels rgb
  color 1
  name Constant3
  xpos 2873
  ypos 432
 }
 Project3D2 {
  inputs 2
  project_on front
  crop false
  name Project3D4
  xpos 2873
  ypos 526
 }
clone $Cb894de00 {
  xpos 2873
  ypos 595
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender7
  xpos 2873
  ypos 877
 }
 Invert {
  name Invert3
  xpos 2873
  ypos 1008
 }
push $N32091c00
clone $Cb894de00 {
  inputs 0
  xpos 2530
  ypos 597
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender8
  xpos 2530
  ypos 813
 }
 Dot {
  name Dot35
  xpos 2564
  ypos 951
 }
set Nff5a7400 [stack 0]
 FilterErode {
  channels all
  name FilterErode3
  xpos 2763
  ypos 942
 }
 Merge2 {
  inputs 2
  operation multiply
  name Multiply2
  xpos 2763
  ypos 1014
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.red 0 0 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.blue 0 2"
  name Shuffle10
  xpos 2763
  ypos 1090
 }
 Grade {
  white 200
  name Grade7
  xpos 2763
  ypos 1188
 }
push $N32091800
push $Nff5a6400
push $N19093800
 Project3D2 {
  inputs 2
  project_on front
  name Project3D5
  xpos 2334
  ypos 491
 }
clone $Cb894de00 {
  xpos 2334
  ypos 598
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel {P.red P.green P.blue}
  N_channel N
  name ScanlineRender9
  xpos 2334
  ypos 748
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  out1 projectionPrev
  fromInput2 {
   {0}
   B
  }
  mappings "3 rgba.red 0 0 projectionPrev.red 0 0 rgba.green 0 1 projectionPrev.green 0 1 rgba.blue 0 2 projectionPrev.blue 0 2"
  name Shuffle12
  xpos 2334
  ypos 1172
 }
push $Nff5a7400
 Dot {
  name Dot36
  xpos 2454
  ypos 951
 }
 Group {
  name NormalsRotate3
  onCreate "\nn=nuke.thisNode()\nn['mblack'].setFlag(0x0000000000000004)\nn['mgain'].setFlag(0x0000000000000004)\nn['mgamma'].setFlag(0x0000000000000004)\n"
  tile_color 0xff00ff
  xpos 2420
  ypos 1057
  addUserKnob {20 User}
  addUserKnob {41 in l "Normals in" t "Select the layer containing the \nnormals" T Shuffle1.in}
  addUserKnob {41 pick l "Pick Plane" T Plane.pick}
  addUserKnob {22 planereset l Reset -STARTLINE T "nuke.thisNode().knob(\"pick\").setValue(0,0)\nnuke.thisNode().knob(\"pick\").setValue(0,1)\nnuke.thisNode().knob(\"pick\").setValue(1,2)"}
  addUserKnob {26 ""}
  addUserKnob {26 divider_2 l "" +STARTLINE T " "}
  addUserKnob {26 manual l "<b>Manual Rotation</b>" -STARTLINE T "  "}
  addUserKnob {22 rotreset l Reset -STARTLINE T "nuke.thisNode().knob(\"yoffset\").setValue(0)\nnuke.thisNode().knob(\"xzrot\").setValue(0)"}
  addUserKnob {7 yoffset l Horizontal t "Rotate around the world Y axis" R -180 180}
  yoffset {{"degrees(atan2(Cam90.world_matrix.2, Cam90.world_matrix.10))"}}
  addUserKnob {7 xzrot l Vertical t "Rotates around the rotated X axis" R -180 180}
  addUserKnob {26 ""}
  addUserKnob {26 matte l "@b;Matte Output" T "      "}
  addUserKnob {6 inv l "Invert    " t "This happens before the matte \ntweaks" -STARTLINE}
  addUserKnob {6 amask l "Mask by Alpha    " -STARTLINE}
  addUserKnob {6 unpre l Unpremult -STARTLINE}
  addUserKnob {7 exp l Exponent t "Exponential falloff" R 1 10}
  exp 2
  addUserKnob {22 expreset l Reset -STARTLINE T "nuke.thisNode().knob(\"exp\").setValue(2)"}
  addUserKnob {7 mblack l Black R -1 1}
  addUserKnob {22 mblackreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mblack\").setValue(0)"}
  addUserKnob {7 mgain l White R 0 4}
  mgain 1
  addUserKnob {22 mgainreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgain\").setValue(1)"}
  addUserKnob {7 mgamma l Gamma R 0 4}
  mgamma 1
  addUserKnob {22 mgammareset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgamma\").setValue(1)"}
  addUserKnob {26 ""}
  addUserKnob {26 "" l mask T ""}
  addUserKnob {41 maskChannelInput l "" -STARTLINE T Merge1.maskChannelInput}
  addUserKnob {41 inject -STARTLINE T Merge1.inject}
  addUserKnob {41 invert_mask l invert -STARTLINE T Merge1.invert_mask}
  addUserKnob {41 fringe -STARTLINE T Merge1.fringe}
  addUserKnob {41 mix T Merge1.mix}
  addUserKnob {20 info l Info}
  addUserKnob {26 infotext l "" +STARTLINE T "W_SuperNormal generates a surface angle based matte using normals.\n\n1. Select the layer containing normals in the dropdown menu.\n2. Enable color picker and pick the point where you want the matte to be white.\n  (I look at the alpha output, hold ctrl+alt and \"glide\" over the surfaces.)\n3. You can also manually rotate the matte. When you colorpick a new point,\n  it is recommended that you reset the manual rotation values to 0.\n"}
  addUserKnob {20 v2_1_group l "v2.1 - Feb 2019" n 1}
  v2_1_group 0
  addUserKnob {26 v2_1_text l "" +STARTLINE T "  -Manual rotation working as originally envisioned: It is more intuitive \n   and faster to reach any desired angle with horizontal(Y) and vertical\n   rotation than with separate XYZ rotations.\n  -General cleanup & refinements.\n"}
  addUserKnob {20 endGroup n -1}
  addUserKnob {20 v2group l "v2.0 - 2018" n 1}
  v2group 0
  addUserKnob {26 v2text l "" +STARTLINE T "  -Adopted a different method for rotating normals shown to me by Daniel Pelc\n  -Simpler math for converting normals into a matte with the help of Erwan Leroy\n"}
  addUserKnob {20 endGroup_1 l endGroup n -1}
  addUserKnob {26 v1_1_text l "" +STARTLINE T "    v1.1 - 2016"}
  addUserKnob {26 ""}
  addUserKnob {26 spacer_1 l "" +STARTLINE T "     "}
  addUserKnob {26 copyright l "&#169;  Wes Heo" -STARTLINE T " "}
 }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.yoffset} 0}
   name Axis10
   label H
   xpos -173
   ypos -163
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {{parent.xzrot} {-degrees(parent.Plane.picked.g)} 0}
   name Axis2
   label V
   xpos -171
   ypos -62
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.Axis2.rotate.y} 0}
   name Axis5
   label V
   xpos -170
   ypos 34
  }
  Input {
   inputs 0
   name Inputmask
   xpos 132
   ypos 544
   number 1
  }
  Input {
   inputs 0
   name N
   xpos 0
   ypos -425
  }
  Shuffle {
   in N
   alpha red2
   out rgb
   name Shuffle1
   xpos 0
   ypos -347
  }
set Nfb335900 [stack 0]
  Dot {
   name Dot1
   xpos 315
   ypos 289
  }
push $Nfb335900
  Unpremult {
   name Unpremult1
   xpos 0
   ypos -286
   disable {{!parent.unpre}}
  }
  NoOp {
   name Plane
   xpos 0
   ypos -218
   addUserKnob {20 User}
   addUserKnob {18 pick l "User Picked Plane" R -1 1}
   pick {0 0 1}
   addUserKnob {6 pick_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
   addUserKnob {20 calc l "Internal Conversions"}
   addUserKnob {18 picked}
   picked {0 {"(atan2(pick.r, pick.b))"} 0}
   addUserKnob {6 picked_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis10.world_matrix.0} {parent.Axis10.world_matrix.1} {parent.Axis10.world_matrix.2}}
        {{parent.Axis10.world_matrix.4} {parent.Axis10.world_matrix.5} {parent.Axis10.world_matrix.6}}
        {{parent.Axis10.world_matrix.8} {parent.Axis10.world_matrix.9} {parent.Axis10.world_matrix.10}}
   }
   name ColorMatrix2
   xpos 0
   ypos -148
   disable {{parent.yoffset==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis2.world_matrix.0} {parent.Axis2.world_matrix.1} {parent.Axis2.world_matrix.2}}
        {{parent.Axis2.world_matrix.4} {parent.Axis2.world_matrix.5} {parent.Axis2.world_matrix.6}}
        {{parent.Axis2.world_matrix.8} {parent.Axis2.world_matrix.9} {parent.Axis2.world_matrix.10}}
   }
   name ColorMatrix3
   xpos 0
   ypos -42
   disable {{parent.xzrot==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis5.world_matrix.0} {parent.Axis5.world_matrix.1} {parent.Axis5.world_matrix.2}}
        {{parent.Axis5.world_matrix.4} {parent.Axis5.world_matrix.5} {parent.Axis5.world_matrix.6}}
        {{parent.Axis5.world_matrix.8} {parent.Axis5.world_matrix.9} {parent.Axis5.world_matrix.10}}
   }
   name ColorMatrix5
   xpos 0
   ypos 54
   disable {{parent.xzrot==0}}
  }
  Expression {
   temp_name0 nx
   temp_expr0 parent.Plane.pick.r
   temp_name1 ny
   temp_expr1 parent.Plane.pick.g
   temp_name2 nz
   temp_expr2 parent.Plane.pick.b
   channel0 {rgba.red -rgba.green -rgba.blue -rgba.alpha}
   expr0 r*nx
   channel1 {-rgba.red rgba.green -rgba.blue none}
   expr1 g*ny
   channel2 {-rgba.red -rgba.green rgba.blue none}
   expr2 b*nz
   channel3 {none none none -rgba.alpha}
   name Expression1
   xpos 0
   ypos 121
   cached true
  }
  Expression {
   expr3 clamp(r+g+b)
   name Expression3
   xpos 0
   ypos 187
  }
  Invert {
   channels alpha
   name Invert1
   xpos 0
   ypos 249
   disable {{!parent.inv}}
  }
  Expression {
   expr3 pow(a,max(1,parent.exp))
   name Expression4
   xpos 0
   ypos 317
  }
  Grade {
   channels alpha
   blackpoint {{-parent.mblack}}
   white {{parent.mgain}}
   gamma {{max(0.001,parent.mgamma)}}
   white_clamp true
   name Grade1
   xpos 0
   ypos 369
  }
  ChannelMerge {
   inputs 2
   operation multiply
   name ChannelMerge1
   xpos 0
   ypos 444
   disable {{!parent.amask}}
  }
push 0
  Merge2 {
   inputs 2+1
   operation copy
   also_merge all
   name Merge1
   label "[ expr { [value mix] == 1 ? \" \" : [concat Mix: [value mix]] } ]"
   xpos 0
   ypos 544
  }
  Output {
   name Output1
   xpos 0
   ypos 623
  }
 end_group
push $Nff5a7400
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.blue 0 2 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.red 0 0"
  name Shuffle13
  xpos 2530
  ypos 993
 }
 Grade {
  channels rgba
  white 0.18
  name Grade8
  xpos 2530
  ypos 1024
 }
 Grade {
  inputs 1+1
  white 4
  name Grade9
  xpos 2530
  ypos 1066
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 projectionPrev
  out1 projectionPrev
  fromInput2 {
   {0}
   B
   A
  }
  in2 rgb
  out2 facingratio
  mappings "6 projectionPrev.red 0 0 projectionPrev.red 0 0 projectionPrev.green 0 1 projectionPrev.green 0 1 projectionPrev.blue 0 2 projectionPrev.blue 0 2 rgba.red 1 0 facingratio.red 1 0 rgba.green 1 1 facingratio.green 1 1 rgba.blue 1 2 facingratio.blue 1 2"
  name Shuffle14
  xpos 2530
  ypos 1172
 }
 Dot {
  name Dot37
  xpos 2564
  ypos 1291
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 rgb
  out1 coverage
  fromInput2 {
   {0}
   B
   A
  }
  mappings "3 rgba.red 0 0 coverage.red 0 0 rgba.green 0 1 coverage.green 0 1 rgba.blue 0 2 coverage.blue 0 2"
  name Shuffle15
  xpos 2763
  ypos 1288
 }
push $Ndac8fc00
 Dot {
  name Dot25
  xpos 1570
  ypos 221
 }
 Dot {
  name Dot10
  xpos 1570
  ypos 334
 }
 Dot {
  name Dot11
  xpos 1200
  ypos 334
 }
 Dot {
  name Dot12
  xpos 1200
  ypos 762
 }
set N14eaa800 [stack 0]
 Dot {
  name Dot13
  xpos 1200
  ypos 827
 }
set N14eaac00 [stack 0]
 Dot {
  name Dot14
  xpos 1200
  ypos 891
 }
push $N668ca00
push 0
 Camera3 {
  inputs 2
  translate {{CAM_45_TRANS}}
  focal 100
  name Cam45
  xpos 1253
  ypos 95
 }
 Dot {
  name Dot22
  xpos 1277
  ypos 222
 }
set Ndac8f400 [stack 0]
 Dot {
  name Dot16
  xpos 1277
  ypos 505
 }
set N14eab400 [stack 0]
 Dot {
  name Dot18
  xpos 1277
  ypos 540
 }
 Constant {
  inputs 0
  channels rgb
  color 1
  name Constant1
  xpos 1957
  ypos 443
 }
 Project3D2 {
  inputs 2
  project_on front
  crop false
  name Project3D2
  xpos 1957
  ypos 537
 }
clone $Cb894de00 {
  xpos 1957
  ypos 606
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender4
  xpos 1957
  ypos 888
 }
 Invert {
  name Invert2
  xpos 1957
  ypos 1019
 }
push $N14eaac00
clone $Cb894de00 {
  inputs 0
  xpos 1614
  ypos 608
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender5
  xpos 1614
  ypos 824
 }
 Dot {
  name Dot19
  xpos 1648
  ypos 962
 }
set N1a611400 [stack 0]
 FilterErode {
  channels all
  name FilterErode2
  xpos 1847
  ypos 953
 }
 Merge2 {
  inputs 2
  operation multiply
  name Multiply1
  xpos 1847
  ypos 1025
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.red 0 0 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.blue 0 2"
  name Shuffle4
  xpos 1847
  ypos 1101
 }
 Grade {
  white 200
  name Grade4
  xpos 1847
  ypos 1199
 }
push $N14eaa800
push $N14eab400
push $N19093400
 Project3D2 {
  inputs 2
  project_on front
  name Project3D3
  xpos 1418
  ypos 502
 }
clone $Cb894de00 {
  xpos 1418
  ypos 609
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel {P.red P.green P.blue}
  N_channel N
  name ScanlineRender6
  xpos 1418
  ypos 759
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  out1 projectionPrev
  fromInput2 {
   {0}
   B
  }
  mappings "3 rgba.red 0 0 projectionPrev.red 0 0 rgba.green 0 1 projectionPrev.green 0 1 rgba.blue 0 2 projectionPrev.blue 0 2"
  name Shuffle5
  xpos 1418
  ypos 1183
 }
push $N1a611400
 Dot {
  name Dot20
  xpos 1538
  ypos 962
 }
 Group {
  name NormalsRotate2
  onCreate "\nn=nuke.thisNode()\nn['mblack'].setFlag(0x0000000000000004)\nn['mgain'].setFlag(0x0000000000000004)\nn['mgamma'].setFlag(0x0000000000000004)\n"
  tile_color 0xff00ff
  xpos 1504
  ypos 1068
  addUserKnob {20 User}
  addUserKnob {41 in l "Normals in" t "Select the layer containing the \nnormals" T Shuffle1.in}
  addUserKnob {41 pick l "Pick Plane" T Plane.pick}
  addUserKnob {22 planereset l Reset -STARTLINE T "nuke.thisNode().knob(\"pick\").setValue(0,0)\nnuke.thisNode().knob(\"pick\").setValue(0,1)\nnuke.thisNode().knob(\"pick\").setValue(1,2)"}
  addUserKnob {26 ""}
  addUserKnob {26 divider_2 l "" +STARTLINE T " "}
  addUserKnob {26 manual l "<b>Manual Rotation</b>" -STARTLINE T "  "}
  addUserKnob {22 rotreset l Reset -STARTLINE T "nuke.thisNode().knob(\"yoffset\").setValue(0)\nnuke.thisNode().knob(\"xzrot\").setValue(0)"}
  addUserKnob {7 yoffset l Horizontal t "Rotate around the world Y axis" R -180 180}
  yoffset {{"degrees(atan2(Cam45.world_matrix.2, Cam45.world_matrix.10))"}}
  addUserKnob {7 xzrot l Vertical t "Rotates around the rotated X axis" R -180 180}
  addUserKnob {26 ""}
  addUserKnob {26 matte l "@b;Matte Output" T "      "}
  addUserKnob {6 inv l "Invert    " t "This happens before the matte \ntweaks" -STARTLINE}
  addUserKnob {6 amask l "Mask by Alpha    " -STARTLINE}
  addUserKnob {6 unpre l Unpremult -STARTLINE}
  addUserKnob {7 exp l Exponent t "Exponential falloff" R 1 10}
  exp 2
  addUserKnob {22 expreset l Reset -STARTLINE T "nuke.thisNode().knob(\"exp\").setValue(2)"}
  addUserKnob {7 mblack l Black R -1 1}
  addUserKnob {22 mblackreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mblack\").setValue(0)"}
  addUserKnob {7 mgain l White R 0 4}
  mgain 1
  addUserKnob {22 mgainreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgain\").setValue(1)"}
  addUserKnob {7 mgamma l Gamma R 0 4}
  mgamma 1
  addUserKnob {22 mgammareset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgamma\").setValue(1)"}
  addUserKnob {26 ""}
  addUserKnob {26 "" l mask T ""}
  addUserKnob {41 maskChannelInput l "" -STARTLINE T Merge1.maskChannelInput}
  addUserKnob {41 inject -STARTLINE T Merge1.inject}
  addUserKnob {41 invert_mask l invert -STARTLINE T Merge1.invert_mask}
  addUserKnob {41 fringe -STARTLINE T Merge1.fringe}
  addUserKnob {41 mix T Merge1.mix}
  addUserKnob {20 info l Info}
  addUserKnob {26 infotext l "" +STARTLINE T "W_SuperNormal generates a surface angle based matte using normals.\n\n1. Select the layer containing normals in the dropdown menu.\n2. Enable color picker and pick the point where you want the matte to be white.\n  (I look at the alpha output, hold ctrl+alt and \"glide\" over the surfaces.)\n3. You can also manually rotate the matte. When you colorpick a new point,\n  it is recommended that you reset the manual rotation values to 0.\n"}
  addUserKnob {20 v2_1_group l "v2.1 - Feb 2019" n 1}
  v2_1_group 0
  addUserKnob {26 v2_1_text l "" +STARTLINE T "  -Manual rotation working as originally envisioned: It is more intuitive \n   and faster to reach any desired angle with horizontal(Y) and vertical\n   rotation than with separate XYZ rotations.\n  -General cleanup & refinements.\n"}
  addUserKnob {20 endGroup n -1}
  addUserKnob {20 v2group l "v2.0 - 2018" n 1}
  v2group 0
  addUserKnob {26 v2text l "" +STARTLINE T "  -Adopted a different method for rotating normals shown to me by Daniel Pelc\n  -Simpler math for converting normals into a matte with the help of Erwan Leroy\n"}
  addUserKnob {20 endGroup_1 l endGroup n -1}
  addUserKnob {26 v1_1_text l "" +STARTLINE T "    v1.1 - 2016"}
  addUserKnob {26 ""}
  addUserKnob {26 spacer_1 l "" +STARTLINE T "     "}
  addUserKnob {26 copyright l "&#169;  Wes Heo" -STARTLINE T " "}
 }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.yoffset} 0}
   name Axis10
   label H
   xpos -173
   ypos -163
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {{parent.xzrot} {-degrees(parent.Plane.picked.g)} 0}
   name Axis2
   label V
   xpos -171
   ypos -62
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.Axis2.rotate.y} 0}
   name Axis5
   label V
   xpos -170
   ypos 34
  }
  Input {
   inputs 0
   name Inputmask
   xpos 132
   ypos 544
   number 1
  }
  Input {
   inputs 0
   name N
   xpos 0
   ypos -425
  }
  Shuffle {
   in N
   alpha red2
   out rgb
   name Shuffle1
   xpos 0
   ypos -347
  }
set Nbcbac300 [stack 0]
  Dot {
   name Dot1
   xpos 315
   ypos 289
  }
push $Nbcbac300
  Unpremult {
   name Unpremult1
   xpos 0
   ypos -286
   disable {{!parent.unpre}}
  }
  NoOp {
   name Plane
   xpos 0
   ypos -218
   addUserKnob {20 User}
   addUserKnob {18 pick l "User Picked Plane" R -1 1}
   pick {0 0 1}
   addUserKnob {6 pick_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
   addUserKnob {20 calc l "Internal Conversions"}
   addUserKnob {18 picked}
   picked {0 {"(atan2(pick.r, pick.b))"} 0}
   addUserKnob {6 picked_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis10.world_matrix.0} {parent.Axis10.world_matrix.1} {parent.Axis10.world_matrix.2}}
        {{parent.Axis10.world_matrix.4} {parent.Axis10.world_matrix.5} {parent.Axis10.world_matrix.6}}
        {{parent.Axis10.world_matrix.8} {parent.Axis10.world_matrix.9} {parent.Axis10.world_matrix.10}}
   }
   name ColorMatrix2
   xpos 0
   ypos -148
   disable {{parent.yoffset==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis2.world_matrix.0} {parent.Axis2.world_matrix.1} {parent.Axis2.world_matrix.2}}
        {{parent.Axis2.world_matrix.4} {parent.Axis2.world_matrix.5} {parent.Axis2.world_matrix.6}}
        {{parent.Axis2.world_matrix.8} {parent.Axis2.world_matrix.9} {parent.Axis2.world_matrix.10}}
   }
   name ColorMatrix3
   xpos 0
   ypos -42
   disable {{parent.xzrot==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis5.world_matrix.0} {parent.Axis5.world_matrix.1} {parent.Axis5.world_matrix.2}}
        {{parent.Axis5.world_matrix.4} {parent.Axis5.world_matrix.5} {parent.Axis5.world_matrix.6}}
        {{parent.Axis5.world_matrix.8} {parent.Axis5.world_matrix.9} {parent.Axis5.world_matrix.10}}
   }
   name ColorMatrix5
   xpos 0
   ypos 54
   disable {{parent.xzrot==0}}
  }
  Expression {
   temp_name0 nx
   temp_expr0 parent.Plane.pick.r
   temp_name1 ny
   temp_expr1 parent.Plane.pick.g
   temp_name2 nz
   temp_expr2 parent.Plane.pick.b
   channel0 {rgba.red -rgba.green -rgba.blue -rgba.alpha}
   expr0 r*nx
   channel1 {-rgba.red rgba.green -rgba.blue none}
   expr1 g*ny
   channel2 {-rgba.red -rgba.green rgba.blue none}
   expr2 b*nz
   channel3 {none none none -rgba.alpha}
   name Expression1
   xpos 0
   ypos 121
   cached true
  }
  Expression {
   expr3 clamp(r+g+b)
   name Expression3
   xpos 0
   ypos 187
  }
  Invert {
   channels alpha
   name Invert1
   xpos 0
   ypos 249
   disable {{!parent.inv}}
  }
  Expression {
   expr3 pow(a,max(1,parent.exp))
   name Expression4
   xpos 0
   ypos 317
  }
  Grade {
   channels alpha
   blackpoint {{-parent.mblack}}
   white {{parent.mgain}}
   gamma {{max(0.001,parent.mgamma)}}
   white_clamp true
   name Grade1
   xpos 0
   ypos 369
  }
  ChannelMerge {
   inputs 2
   operation multiply
   name ChannelMerge1
   xpos 0
   ypos 444
   disable {{!parent.amask}}
  }
push 0
  Merge2 {
   inputs 2+1
   operation copy
   also_merge all
   name Merge1
   label "[ expr { [value mix] == 1 ? \" \" : [concat Mix: [value mix]] } ]"
   xpos 0
   ypos 544
  }
  Output {
   name Output1
   xpos 0
   ypos 623
  }
 end_group
push $Nff5a7400
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.blue 0 2 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.red 0 0"
  name Shuffle13
  xpos 2530
  ypos 993
 }
 Grade {
  channels rgba
  white 0.18
  name Grade8
  xpos 2530
  ypos 1024
 }
 Grade {
  inputs 1+1
  white 4
  name Grade9
  xpos 2530
  ypos 1066
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 projectionPrev
  out1 projectionPrev
  fromInput2 {
   {0}
   B
   A
  }
  in2 rgb
  out2 facingratio
  mappings "6 projectionPrev.red 0 0 projectionPrev.red 0 0 projectionPrev.green 0 1 projectionPrev.green 0 1 projectionPrev.blue 0 2 projectionPrev.blue 0 2 rgba.red 1 0 facingratio.red 1 0 rgba.green 1 1 facingratio.green 1 1 rgba.blue 1 2 facingratio.blue 1 2"
  name Shuffle14
  xpos 2530
  ypos 1172
 }
 Dot {
  name Dot37
  xpos 2564
  ypos 1291
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 rgb
  out1 coverage
  fromInput2 {
   {0}
   B
   A
  }
  mappings "3 rgba.red 0 0 coverage.red 0 0 rgba.green 0 1 coverage.green 0 1 rgba.blue 0 2 coverage.blue 0 2"
  name Shuffle15
  xpos 2763
  ypos 1288
 }
push $Ndac8fc00
 Dot {
  name Dot25
  xpos 1570
  ypos 221
 }
 Dot {
  name Dot10
  xpos 1570
  ypos 334
 }
 Dot {
  name Dot11
  xpos 1200
  ypos 334
 }
 Dot {
  name Dot12
  xpos 1200
  ypos 762
 }
set N14eaa800 [stack 0]
 Dot {
  name Dot13
  xpos 1200
  ypos 827
 }
set N14eaac00 [stack 0]
 Dot {
  name Dot14
  xpos 1200
  ypos 891
 }
push $N668ca00
push 0
 Camera3 {
  inputs 2
  translate {{CAM_45_TRANS}}
  focal 100
  name Cam45
  xpos 1253
  ypos 95
 }
 Dot {
  name Dot22
  xpos 1277
  ypos 222
 }
set Ndac8f400 [stack 0]
 Dot {
  name Dot16
  xpos 1277
  ypos 505
 }
set N14eab400 [stack 0]
 Dot {
  name Dot18
  xpos 1277
  ypos 540
 }
 Constant {
  inputs 0
  channels rgb
  color 1
  name Constant1
  xpos 1957
  ypos 443
 }
 Project3D2 {
  inputs 2
  project_on front
  crop false
  name Project3D2
  xpos 1957
  ypos 537
 }
clone $Cb894de00 {
  xpos 1957
  ypos 606
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender4
  xpos 1957
  ypos 888
 }
 Invert {
  name Invert2
  xpos 1957
  ypos 1019
 }
push $N14eaac00
clone $Cb894de00 {
  inputs 0
  xpos 1614
  ypos 608
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel P
  N_channel N
  name ScanlineRender5
  xpos 1614
  ypos 824
 }
 Dot {
  name Dot19
  xpos 1648
  ypos 962
 }
set N1a611400 [stack 0]
 FilterErode {
  channels all
  name FilterErode2
  xpos 1847
  ypos 953
 }
 Merge2 {
  inputs 2
  operation multiply
  name Multiply1
  xpos 1847
  ypos 1025
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.red 0 0 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.blue 0 2"
  name Shuffle4
  xpos 1847
  ypos 1101
 }
 Grade {
  white 200
  name Grade4
  xpos 1847
  ypos 1199
 }
push $N14eaa800
push $N14eab400
push $N19093400
 Project3D2 {
  inputs 2
  project_on front
  name Project3D3
  xpos 1418
  ypos 502
 }
clone $Cb894de00 {
  xpos 1418
  ypos 609
  selected false
 }
push 0
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel {P.red P.green P.blue}
  N_channel N
  name ScanlineRender6
  xpos 1418
  ypos 759
 }
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  out1 projectionPrev
  fromInput2 {
   {0}
   B
  }
  mappings "3 rgba.red 0 0 projectionPrev.red 0 0 rgba.green 0 1 projectionPrev.green 0 1 rgba.blue 0 2 projectionPrev.blue 0 2"
  name Shuffle5
  xpos 1418
  ypos 1183
 }
push $N1a611400
 Dot {
  name Dot20
  xpos 1538
  ypos 962
 }
 Group {
  name NormalsRotate2
  onCreate "\nn=nuke.thisNode()\nn['mblack'].setFlag(0x0000000000000004)\nn['mgain'].setFlag(0x0000000000000004)\nn['mgamma'].setFlag(0x0000000000000004)\n"
  tile_color 0xff00ff
  xpos 1504
  ypos 1068
  addUserKnob {20 User}
  addUserKnob {41 in l "Normals in" t "Select the layer containing the \nnormals" T Shuffle1.in}
  addUserKnob {41 pick l "Pick Plane" T Plane.pick}
  addUserKnob {22 planereset l Reset -STARTLINE T "nuke.thisNode().knob(\"pick\").setValue(0,0)\nnuke.thisNode().knob(\"pick\").setValue(0,1)\nnuke.thisNode().knob(\"pick\").setValue(1,2)"}
  addUserKnob {26 ""}
  addUserKnob {26 divider_2 l "" +STARTLINE T " "}
  addUserKnob {26 manual l "<b>Manual Rotation</b>" -STARTLINE T "  "}
  addUserKnob {22 rotreset l Reset -STARTLINE T "nuke.thisNode().knob(\"yoffset\").setValue(0)\nnuke.thisNode().knob(\"xzrot\").setValue(0)"}
  addUserKnob {7 yoffset l Horizontal t "Rotate around the world Y axis" R -180 180}
  yoffset {{"degrees(atan2(Cam45.world_matrix.2, Cam45.world_matrix.10))"}}
  addUserKnob {7 xzrot l Vertical t "Rotates around the rotated X axis" R -180 180}
  addUserKnob {26 ""}
  addUserKnob {26 matte l "@b;Matte Output" T "      "}
  addUserKnob {6 inv l "Invert    " t "This happens before the matte \ntweaks" -STARTLINE}
  addUserKnob {6 amask l "Mask by Alpha    " -STARTLINE}
  addUserKnob {6 unpre l Unpremult -STARTLINE}
  addUserKnob {7 exp l Exponent t "Exponential falloff" R 1 10}
  exp 2
  addUserKnob {22 expreset l Reset -STARTLINE T "nuke.thisNode().knob(\"exp\").setValue(2)"}
  addUserKnob {7 mblack l Black R -1 1}
  addUserKnob {22 mblackreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mblack\").setValue(0)"}
  addUserKnob {7 mgain l White R 0 4}
  mgain 1
  addUserKnob {22 mgainreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgain\").setValue(1)"}
  addUserKnob {7 mgamma l Gamma R 0 4}
  mgamma 1
  addUserKnob {22 mgammareset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgamma\").setValue(1)"}
  addUserKnob {26 ""}
  addUserKnob {26 "" l mask T ""}
  addUserKnob {41 maskChannelInput l "" -STARTLINE T Merge1.maskChannelInput}
  addUserKnob {41 inject -STARTLINE T Merge1.inject}
  addUserKnob {41 invert_mask l invert -STARTLINE T Merge1.invert_mask}
  addUserKnob {41 fringe -STARTLINE T Merge1.fringe}
  addUserKnob {41 mix T Merge1.mix}
  addUserKnob {20 info l Info}
  addUserKnob {26 infotext l "" +STARTLINE T "W_SuperNormal generates a surface angle based matte using normals.\n\n1. Select the layer containing normals in the dropdown menu.\n2. Enable color picker and pick the point where you want the matte to be white.\n  (I look at the alpha output, hold ctrl+alt and \"glide\" over the surfaces.)\n3. You can also manually rotate the matte. When you colorpick a new point,\n  it is recommended that you reset the manual rotation values to 0.\n"}
  addUserKnob {20 v2_1_group l "v2.1 - Feb 2019" n 1}
  v2_1_group 0
  addUserKnob {26 v2_1_text l "" +STARTLINE T "  -Manual rotation working as originally envisioned: It is more intuitive \n   and faster to reach any desired angle with horizontal(Y) and vertical\n   rotation than with separate XYZ rotations.\n  -General cleanup & refinements.\n"}
  addUserKnob {20 endGroup n -1}
  addUserKnob {20 v2group l "v2.0 - 2018" n 1}
  v2group 0
  addUserKnob {26 v2text l "" +STARTLINE T "  -Adopted a different method for rotating normals shown to me by Daniel Pelc\n  -Simpler math for converting normals into a matte with the help of Erwan Leroy\n"}
  addUserKnob {20 endGroup_1 l endGroup n -1}
  addUserKnob {26 v1_1_text l "" +STARTLINE T "    v1.1 - 2016"}
  addUserKnob {26 ""}
  addUserKnob {26 spacer_1 l "" +STARTLINE T "     "}
  addUserKnob {26 copyright l "&#169;  Wes Heo" -STARTLINE T " "}
 }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.yoffset} 0}
   name Axis10
   label H
   xpos -173
   ypos -163
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {{parent.xzrot} {-degrees(parent.Plane.picked.g)} 0}
   name Axis2
   label V
   xpos -171
   ypos -62
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.Axis2.rotate.y} 0}
   name Axis5
   label V
   xpos -170
   ypos 34
  }
  Input {
   inputs 0
   name Inputmask
   xpos 132
   ypos 544
   number 1
  }
  Input {
   inputs 0
   name N
   xpos 0
   ypos -425
  }
  Shuffle {
   in N
   alpha red2
   out rgb
   name Shuffle1
   xpos 0
   ypos -347
  }
set Nbcbac300 [stack 0]
  Dot {
   name Dot1
   xpos 315
   ypos 289
  }
push $Nbcbac300
  Unpremult {
   name Unpremult1
   xpos 0
   ypos -286
   disable {{!parent.unpre}}
  }
  NoOp {
   name Plane
   xpos 0
   ypos -218
   addUserKnob {20 User}
   addUserKnob {18 pick l "User Picked Plane" R -1 1}
   pick {0 0 1}
   addUserKnob {6 pick_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
   addUserKnob {20 calc l "Internal Conversions"}
   addUserKnob {18 picked}
   picked {0 {"(atan2(pick.r, pick.b))"} 0}
   addUserKnob {6 picked_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis10.world_matrix.0} {parent.Axis10.world_matrix.1} {parent.Axis10.world_matrix.2}}
        {{parent.Axis10.world_matrix.4} {parent.Axis10.world_matrix.5} {parent.Axis10.world_matrix.6}}
        {{parent.Axis10.world_matrix.8} {parent.Axis10.world_matrix.9} {parent.Axis10.world_matrix.10}}
   }
   name ColorMatrix2
   xpos 0
   ypos -148
   disable {{parent.yoffset==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis2.world_matrix.0} {parent.Axis2.world_matrix.1} {parent.Axis2.world_matrix.2}}
        {{parent.Axis2.world_matrix.4} {parent.Axis2.world_matrix.5} {parent.Axis2.world_matrix.6}}
        {{parent.Axis2.world_matrix.8} {parent.Axis2.world_matrix.9} {parent.Axis2.world_matrix.10}}
   }
   name ColorMatrix3
   xpos 0
   ypos -42
   disable {{parent.xzrot==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis5.world_matrix.0} {parent.Axis5.world_matrix.1} {parent.Axis5.world_matrix.2}}
        {{parent.Axis5.world_matrix.4} {parent.Axis5.world_matrix.5} {parent.Axis5.world_matrix.6}}
        {{parent.Axis5.world_matrix.8} {parent.Axis5.world_matrix.9} {parent.Axis5.world_matrix.10}}
   }
   name ColorMatrix5
   xpos 0
   ypos 54
   disable {{parent.xzrot==0}}
  }
  Expression {
   temp_name0 nx
   temp_expr0 parent.Plane.pick.r
   temp_name1 ny
   temp_expr1 parent.Plane.pick.g
   temp_name2 nz
   temp_expr2 parent.Plane.pick.b
   channel0 {rgba.red -rgba.green -rgba.blue -rgba.alpha}
   expr0 r*nx
   channel1 {-rgba.red rgba.green -rgba.blue none}
   expr1 g*ny
   channel2 {-rgba.red -rgba.green rgba.blue none}
   expr2 b*nz
   channel3 {none none none -rgba.alpha}
   name Expression1
   xpos 0
   ypos 121
   cached true
  }
  Expression {
   expr3 clamp(r+g+b)
   name Expression3
   xpos 0
   ypos 187
  }
  Invert {
   channels alpha
   name Invert1
   xpos 0
   ypos 249
   disable {{!parent.inv}}
  }
  Expression {
   expr3 pow(a,max(1,parent.exp))
   name Expression4
   xpos 0
   ypos 317
  }
  Grade {
   channels alpha
   blackpoint {{-parent.mblack}}
   white {{parent.mgain}}
   gamma {{max(0.001,parent.mgamma)}}
   white_clamp true
   name Grade1
   xpos 0
   ypos 369
  }
  ChannelMerge {
   inputs 2
   operation multiply
   name ChannelMerge1
   xpos 0
   ypos 444
   disable {{!parent.amask}}
  }
push 0
  Merge2 {
   inputs 2+1
   operation copy
   also_merge all
   name Merge1
   label "[ expr { [value mix] == 1 ? \" \" : [concat Mix: [value mix]] } ]"
   xpos 0
   ypos 544
  }
  Output {
   name Output1
   xpos 0
   ypos 623
  }
 end_group
push $Nbaa2cc00
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.blue 0 2 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.red 0 0"
  name Shuffle9
  xpos 698
  ypos 1002
 }
 Grade {
  channels rgba
  white 0.18
  name Grade3
  xpos 698
  ypos 1033
 }
 Grade {
  inputs 1+1
  white 4
  name Grade2
  xpos 698
  ypos 1066
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 projectionPrev
  out1 projectionPrev
  fromInput2 {
   {0}
   B
   A
  }
  in2 rgb
  out2 facingratio
  mappings "6 projectionPrev.red 0 0 projectionPrev.red 0 0 projectionPrev.green 0 1 projectionPrev.green 0 1 projectionPrev.blue 0 2 projectionPrev.blue 0 2 rgba.red 1 0 facingratio.red 1 0 rgba.green 1 1 facingratio.green 1 1 rgba.blue 1 2 facingratio.blue 1 2"
  name Shuffle2
  xpos 698
  ypos 1181
 }
 Dot {
  name Dot6
  xpos 732
  ypos 1300
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {1}
   B
   A
  }
  in1 rgb
  out1 coverage
  fromInput2 {
   {0}
   B
   A
  }
  mappings "3 rgba.red 0 0 coverage.red 0 0 rgba.green 0 1 coverage.green 0 1 rgba.blue 0 2 coverage.blue 0 2"
  name Shuffle3
  xpos 931
  ypos 1297
 }
 Dot {
  name Dot98
  xpos 965
  ypos 1432
 }
 Switch {
  inputs 7
  name Switch1
  xpos 6427
  ypos 1603
 }
 Output {
  name Output1
  xpos 6427
  ypos 1888
 }
 Viewer {
  frame_range 1001-1180
  viewerProcess "ACES 1.0 SDR-video (sRGB Display)"
  monitorOutNDISenderName "Nuke - Charon_projection_test_v07 - Viewer1"
  name Viewer1
  xpos 6427
  ypos 2186
 }
end_group"""