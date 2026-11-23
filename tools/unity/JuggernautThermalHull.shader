// Thin red silhouette contour, drawn inside the camera's own render like visible-only chams.
// Uses stencil bit 0x40 (Unity's deferred path already marks all geometry with 0x80).
// Pass 0 (clear): full-screen triangle that clears bit 0x40.
// Pass 1 (mark):  every target mesh sets bit 0x40 where it is visible (normal depth test, no colour).
// Pass 2 (hull):  an inverted hull, extruded by _Width pixels in screen space, drawn only where bit 0x40 is NOT set,
//                 so only the outer silhouette remains. Walls occlude it through the normal depth test.
Shader "Hidden/Juggernaut/ThermalHull"
{
    Properties
    {
        _OutlineColor ("Outline Color", Color) = (1, 0.1, 0.1, 1)
        _Width ("Width (pixels)", Float) = 1.0
    }
    SubShader
    {
        Tags { "Queue" = "Overlay" "RenderType" = "Opaque" }

        Pass
        {
            Name "CLEAR"
            Cull Off
            ZWrite Off
            ZTest Always
            ColorMask 0
            Stencil
            {
                Ref 0
                ReadMask 64
                WriteMask 64
                Comp Always
                Pass Replace
            }

            CGPROGRAM
            #pragma target 3.0
            #pragma vertex Vert
            #pragma fragment Frag
            #include "UnityCG.cginc"

            float4 Vert(uint id : SV_VertexID) : SV_POSITION
            {
                float2 uv = float2((id << 1) & 2, id & 2);
                return float4(uv * 2 - 1, 0.5, 1);
            }

            fixed4 Frag() : SV_Target { return 0; }
            ENDCG
        }

        Pass
        {
            Name "MARK"
            Cull Off
            ZWrite Off
            ZTest LEqual
            ColorMask 0
            Stencil
            {
                Ref 64
                ReadMask 64
                WriteMask 64
                Comp Always
                Pass Replace
            }

            CGPROGRAM
            #pragma target 3.0
            #pragma vertex Vert
            #pragma fragment Frag
            #include "UnityCG.cginc"

            float4 Vert(float4 vertex : POSITION) : SV_POSITION { return UnityObjectToClipPos(vertex); }
            fixed4 Frag() : SV_Target { return 0; }
            ENDCG
        }

        Pass
        {
            Name "HULL"
            Cull Front
            ZWrite Off
            ZTest LEqual
            ColorMask RGB
            Stencil
            {
                Ref 64
                ReadMask 64
                WriteMask 64
                Comp NotEqual
                Pass Keep
            }

            CGPROGRAM
            #pragma target 3.0
            #pragma vertex Vert
            #pragma fragment Frag
            #include "UnityCG.cginc"

            fixed4 _OutlineColor;
            float _Width;

            struct Attributes
            {
                float4 vertex : POSITION;
                float3 normal : NORMAL;
            };

            float4 Vert(Attributes input) : SV_POSITION
            {
                float4 clip = UnityObjectToClipPos(input.vertex);
                float3 viewNormal = mul((float3x3)UNITY_MATRIX_IT_MV, input.normal);
                float2 dir = mul((float2x2)UNITY_MATRIX_P, viewNormal.xy);
                float len = length(dir);
                if (len > 1e-5)
                    clip.xy += (dir / len) * (_Width * 2.0 / _ScreenParams.xy) * clip.w;
                return clip;
            }

            fixed4 Frag() : SV_Target { return _OutlineColor; }
            ENDCG
        }
    }
    Fallback Off
}
